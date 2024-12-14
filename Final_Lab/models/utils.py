import os
import json
import random
import numpy as np
import torch
import torch.nn as nn
from torch.optim import AdamW

from dataclasses import dataclass, field
from collections import defaultdict
from typing import List, Union, Any
from collections.abc import Mapping
from .dataset import KUAKE_Dataset
import argparse
from transformers.trainer_pt_utils import get_parameter_names
from transformers.optimization import get_linear_schedule_with_warmup, get_cosine_schedule_with_warmup, get_constant_schedule_with_warmup

MODEL_DIR = "hfl/chinese-bert-wwm-ext"
DATA_DIR = "../data"
OUTPUT_DIR = "./output_data"
TASK_NAME = "KUAKE-QQR"
MAX_LENGTH = 64
BATCH_SIZE = 4
EPOCHS = 3
LABELS = 3
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class DataTrainingArguments:

    model_dir: str = field(
        default= MODEL_DIR,
        metadata={'help': 'The pretrained model directory'}
    )
    data_dir: str = field(
        default=DATA_DIR,
        metadata={'help': 'The data directory'}
    )
    max_length: int = field(
        default=MAX_LENGTH,
        metadata={'help': 'Maximum sequence length allowed to input'}
    )

    task_name: str = field(
        default=TASK_NAME,
        metadata={'help': 'The name of the task to train on'}
    )

    labels: int = field(
        default=LABELS,
        metadata={'help': 'The number of labels in the dataset'}
    )

    argument: bool = field(
        default=False,
        metadata={"help": "Whether to use argument data"}
    )

    def __str__(self):
        self_as_dict = dataclasses.asdict(self)
        attrs_as_str = [f"{k}={v},\n" for k, v in sorted(self_as_dict.items())]
        return f"{self.__class__.__name__}(\n{''.join(attrs_as_str)})"
        
    def to_json_string(self):
        """Serializes this instance to a JSON string."""
        return json.dumps(dataclasses.asdict(self), indent=2) + "\n"

@dataclass
class TrainingArguments:

    output_dir: str = field(
        default='output_data/',
        metadata={'help': 'The output directory where the model predictions and checkpoints will be written.'}
    )
    train_batch_size: int = field(
        default=BATCH_SIZE,
        metadata={'help': 'batch size for training'}
    )
    eval_batch_size: int = field(
        default=1,
        metadata={'help': 'batch size for evaluation'}
    )

    scheduler: str = field(
        default="linear",
        metadata={'help': 'The scheduler to use for training.'}
    )

    gradient_accumulation_steps: int = field(
        default=1,
        metadata={'help': 'Number of updates steps to accumulate before performing a backward/update pass.'}
    )
    num_train_epochs: int = field(
        default=EPOCHS,
        metadata={"help": "The total number of training epochs"}
    )
    learning_rate: float = field(
        default=3e-5,
        metadata={'help': '"The initial learning rate for AdamW.'}
    )
    weight_decay: float = field(
        default=0.0,
        metadata={"help": "Weight decay for AdamW"}
    )
    warmup_ratio: float = field(
        default=0.05,
        metadata={"help": "Linear warmup over warmup_ratio fraction of total steps."}
    )
    dataloader_num_workers: int = field(
        default=0,
        metadata={"help": "Number of subprocesses to use for data loading (PyTorch only)"}
    )
    
    logging_steps: int = field(
        default=100,
        metadata={'help': 'logging states every X updates steps.'}
    )
    eval_steps: int = field(
        default=50,
        metadata={'help': 'Run an evaluation every X steps.'}
    )
    device: str = field(
        default= "cuda" if torch.cuda.is_available() else "cpu",
        metadata={"help": 'The device used for training'}
    )

    tolerance: float = field(
        default=0.1,
        metadata={"help": "Tolerance for early stopping"}
    )

    def get_warmup_steps(self, num_training_steps):
        return int(num_training_steps * self.warmup_ratio)

    def __str__(self):
        self_as_dict = dataclasses.asdict(self)
        attrs_as_str = [f"{k}={v},\n" for k, v in sorted(self_as_dict.items())]
        return f"{self.__class__.__name__}(\n{''.join(attrs_as_str)})"
        
    def to_json_string(self):
        """Serializes this instance to a JSON string."""
        return json.dumps(dataclasses.asdict(self), indent=2) + "\n"

def args_parser():
    parser = argparse.ArgumentParser(description="PyTorch Question-Keyword Matching Training")

    parser.add_argument("--local_rank", type=int, default=0, help="Local rank for distributed training.")

    parser.add_argument("--model-dir", '-m', default=MODEL_DIR, type=str, help="The pretrained model directory")
    parser.add_argument("--data-dir", '-d', default=DATA_DIR, type=str, help="The data directory")
    parser.add_argument("--output-dir", '-o', default=OUTPUT_DIR, type=str, help="The output directory where the model predictions and checkpoints will be written.")

    parser.add_argument("--epochs", '-n', default=EPOCHS, type=int, help="The total number of training epochs")
    parser.add_argument("--batch-size", '-b', default=BATCH_SIZE, type=int, help="batch size for training")
    parser.add_argument("--scheduler", '-s', default="linear", type=str, help="The scheduler to use for training.", choices=["linear", "cosine", "constant"])

    parser.add_argument("--learning-rate", '-lr', default=3e-5, type=float, help="The initial learning rate for AdamW.")
    parser.add_argument("--weight-decay", '-wd', default=0.0, type=float, help="Weight decay for AdamW")
    parser.add_argument("--warmup-ratio", '-wr', default=0.05, type=float, help="Linear warmup over warmup_ratio fraction of total steps.")

    parser.add_argument("--tolerance", '-tol', default=0.1, type=float, help="Tolerance for early stopping")
    parser.add_argument("--tag", '-tag', default=None, type=str, help="The tag of the model")

    parser.add_argument("--argument", action="store_true", help="Whether to use argument data")

    return parser.parse_args()


def set_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True 
    torch.backends.cudnn.benchmark = False



def create_optimizer_and_scheduler(
    args: TrainingArguments,
    model: nn.Module,
    num_training_steps: int):

    decay_parameters = get_parameter_names(model, [nn.LayerNorm])
    decay_parameters = [name for name in decay_parameters if "bias" not in name]
    optimizer_grouped_parameters = [
        {
            "params": [p for n, p in model.named_parameters() if n in decay_parameters],
            "weight_decay": args.weight_decay,
        },
        {
            "params": [p for n, p in model.named_parameters() if n not in decay_parameters],
            "weight_decay": 0.0,
        },
    ]

    optimizer = AdamW(
        optimizer_grouped_parameters, 
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )
    if args.scheduler == "linear":
        print("Using linear scheduler")
        scheduler = get_linear_schedule_with_warmup(
            optimizer, 
            num_training_steps=num_training_steps, 
            num_warmup_steps=args.get_warmup_steps(num_training_steps)
        )
    elif args.scheduler == "cosine":
        print("Using cosine scheduler")
        scheduler = get_cosine_schedule_with_warmup(
            optimizer, 
            num_training_steps=num_training_steps,
            num_warmup_steps=args.get_warmup_steps(num_training_steps)
        )
    elif args.scheduler == "constant":
        print("Using constant scheduler")
        scheduler = get_constant_schedule_with_warmup(
            optimizer, 
            num_warmup_steps=args.get_warmup_steps(num_training_steps)
        )

    return optimizer, scheduler


def load_data(data_dir, task_name, argument = False):
    dir_path = os.path.join(data_dir, task_name)
    train_path = os.path.join(dir_path, f"{task_name}_train.json")
    dev_path = os.path.join(dir_path, f"{task_name}_dev.json")
    test_path = os.path.join(dir_path, f"{task_name}_test.json")

    def read_file(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def preprocess_train_dev(samples, type_='train'):
        grouped_data = defaultdict(lambda: [[], []])
        for sample in samples:
            label = sample.get("label", None)
            if label == "NA":
                continue
            try:
                label = int(label)
            except (ValueError, TypeError):
                continue
            query1 = sample["query1"]
            query2 = sample["query2"]
            grouped_data[query1][0].append(query2)
            grouped_data[query1][1].append(label)
        

        new_grouped_data = defaultdict(lambda: [[], []])
        if argument and type_ == 'train':
            for query, keys in grouped_data.items():
                key, label = keys
                key2, key1, key0 = [], [], []
                for i in range(len(label)):
                    if label[i] == 2:
                        key2.append(key[i])
                    elif label[i] == 1:
                        key1.append(key[i])
                    else:
                        key0.append(key[i])

                for i in range(len(key2)):
                    for j in range(i+1, len(key2)):
                        new_grouped_data[key2[i]][0].append(key2[j])
                        new_grouped_data[key2[i]][1].append(2)

                        new_grouped_data[key2[j]][0].append(key2[i])
                        new_grouped_data[key2[j]][1].append(2)
                    
                    for j in range(len(key1)):
                        new_grouped_data[key2[i]][0].append(key1[j])
                        new_grouped_data[key2[i]][1].append(1)

                        new_grouped_data[key1[j]][0].append(key2[i])
                        new_grouped_data[key1[j]][1].append(0)
                    
                    for j in range(len(key0)):
                        new_grouped_data[key2[i]][0].append(key0[j])
                        new_grouped_data[key2[i]][1].append(0)

        grouped_data.update(new_grouped_data)
        for query1, keys in grouped_data.items():
            find_quary = False
            for quary2 in keys[0]:
                if quary2 == query1:
                    find_quary = True
                    break
            
            if not find_quary:
                keys[0].append(query1)
                keys[1].append(2)

        
        # 转换为列表形式
        processed_samples = [{
            "query": query1,
            "keys": keys[0],
            "label": keys[1]
        } for query1, keys in grouped_data.items()]
        return processed_samples

    def preprocess_test(samples):
        grouped_data = defaultdict(list)
        processed_samples = []
        for sample in samples:
            processed_samples.append({
                "query": sample["query1"],
                "keys": [sample["query2"]],
                "id": sample["id"]
            })
        return processed_samples

    def load_and_preprocess(file_path, type_='train'):
        data = read_file(file_path)
        if type_ == 'test':
            return preprocess_test(data)
        return preprocess_train_dev(data, type_)


    return {
        "train": load_and_preprocess(train_path, type_='train'),
        "valid": load_and_preprocess(dev_path, type_='valid'),
        "test": load_and_preprocess(test_path, type_='test')
    }

def prepare_input(data: Union[torch.Tensor, Any], device: str = 'cuda'):
    """
    Prepares one `data` before feeding it to the model, be it a tensor or a nested list/dictionary of tensors.
    """
    if isinstance(data, Mapping):
        return type(data)({k: prepare_input(v, device) for k, v in data.items()})
    elif isinstance(data, (tuple, list)):
        return type(data)(prepare_input(v, device) for v in data)
    elif isinstance(data, torch.Tensor):
        kwargs = dict(device=device)
        return data.to(**kwargs)
    return data

def generate_commit(output_dir, task_name, test_dataset, preds: List[int]):
    pred_test_examples = []
    for idx in range(len(test_dataset)):
        example = test_dataset[idx]
        label  = KUAKE_Dataset.id2label(preds[idx])
        pred_example = {'id': example['id'], 'query1': example['query'], 'query2': example['keys'][0], 'label': label}
        pred_test_examples.append(pred_example)
    
    with open(os.path.join(output_dir, f'{task_name}_test.json'), 'w', encoding='utf-8') as f:
        json.dump(pred_test_examples, f, indent=2, ensure_ascii=False)
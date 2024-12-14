from transformers import AutoTokenizer
import os
import time 
import json
import torch
import torch.nn as nn
import random
import numpy as np
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

from torch.utils.tensorboard import SummaryWriter

from models.utils import *
from models.dataset import *
from models.model import ContrastiveModel

def train(model, data, optimizer, scheduler, device):
    model.train()

    optimizer.zero_grad()
    data = data.to(device)
    labals = data.labels
    correct = 0
    # 前向传播
    logits = model(data)
    nums = 0
    loss = model.criterion(data, logits)
    # correct = (torch.argmax(logits, dim=1) == labals).sum().item()
    # correct /= len(labals)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

    optimizer.step()
    scheduler.step()
    return loss.item(), correct

# 定义评估函数
def evaluate(model, dataloader, device):
    model.eval()
    eval_correct = 0
    eval_loss = 0.0
    with torch.no_grad():
        with tqdm(dataloader, desc="Evaluation", leave=False) as pbar:
            for data in dataloader:
                data = data.to(device)
                labels = data.labels
                # 前向传播
                logits = model(data)
                loss = model.criterion(data, logits).item()
                # correct = (torch.argmax(logits, dim=1) == labels).sum().item()
                # eval_correct += correct/len(labels)
                eval_loss += loss   
                pbar.update(1)
                
    return eval_loss/len(dataloader), eval_correct/len(dataloader)

def predict(
    args: TrainingArguments,
    model: nn.Module,
    test_dataloader
):
    model.eval()
    preds_list = []
    with torch.no_grad():
        with tqdm(test_dataloader, desc="Predicting") as pbar:
            for item in test_dataloader:
                inputs = item.to(args.device)
                outputs = model(inputs)

                preds = torch.argmax(outputs.cpu(), dim=-1).numpy()
                preds_list.append(preds)
                pbar.update(1)

    print(f'Prediction Finished!')
    preds = np.concatenate(preds_list, axis=0).tolist()

    return preds

def train_model(model, train_loader, valid_loader, train_args, tokenizer, writer):
    # 定义损失函数和优化器
    optimizer, scheduler = create_optimizer_and_scheduler(train_args, model, len(train_loader) * train_args.num_train_epochs)
    # 开始训练
    val_loss = 0
    val_acc = 0
    best_steps = 0
    final_loss = 0
    with tqdm(range(train_args.num_train_epochs* len(train_loader)), desc="Epochs") as epochs_pbar:
        global_steps = 0
        for epoch in range(train_args.num_train_epochs):
            epoch_loss= 0
            epoch_correct = 0
            epoch_total = 0

            for batch in train_loader:
                global_steps += 1
                
                train_loss, train_acc = train(model, batch, optimizer, scheduler, train_args.device)
                epoch_loss += train_loss
                epoch_correct += train_acc
                epoch_total += 1
                
                if (global_steps+1) % train_args.eval_steps == 0:
                    
                    val_loss, val_acc = evaluate(model, valid_loader, train_args.device)

                    writer.add_scalar("Loss/train", epoch_loss / epoch_total, global_steps)
                    # writer.add_scalar("Accuracy/train", epoch_correct / epoch_total, global_steps)
                    writer.add_scalar("Loss/eval", val_loss, global_steps)
                    # writer.add_scalar("Accuracy/eval", val_acc, global_steps)

                    writer.add_scalar("Learning Rate", scheduler.get_last_lr()[0], global_steps)

                    final_loss = val_loss
                
                epochs_pbar.set_postfix({
                    "train loss": epoch_loss / epoch_total,
                    # "train acc": epoch_correct / epoch_total,
                    "eval loss": val_loss,
                    # "eval acc": val_acc
                })
                epochs_pbar.update(1)

        final_steps = epoch
        os.makedirs(train_args.output_dir, exist_ok=True)
        save_dir = train_args.output_dir
        
        model.encoder.save_pretrained(save_dir)
        torch.save(model.state_dict(), os.path.join(save_dir, "model.pth"))
        tokenizer.save_pretrained(save_directory=save_dir)
        print(f"Model saved at {save_dir}")
    return final_loss, final_steps


def main(args):
    data_args = DataTrainingArguments(data_dir=args.data_dir, model_dir=args.model_dir)
    train_args = TrainingArguments(output_dir=args.output_dir, 
                            num_train_epochs=args.epochs, 
                            train_batch_size=args.batch_size, 
                            learning_rate=args.learning_rate, 
                            weight_decay=args.weight_decay, 
                            warmup_ratio=args.warmup_ratio,
                            tolerance=args.tolerance,
                            scheduler=args.scheduler)

    timename = time.strftime("%Y-%m-%d-%H-%M", time.localtime())
    model_name = 'bert'
    if args.tag:
        timename = f"{args.tag}-{timename}"
    train_args.output_dir = os.path.join(train_args.output_dir, model_name, timename)

    writer = SummaryWriter(log_dir=train_args.output_dir)

    tokenizer = AutoTokenizer.from_pretrained(data_args.model_dir)

    rawdata = load_data(data_args.data_dir, data_args.task_name)

    train_dataset = KUAKE_Dataset(rawdata["train"], tokenizer, max_length=data_args.max_length, type_='train')
    valid_dataset = KUAKE_Dataset(rawdata["valid"], tokenizer, max_length=data_args.max_length, type_='valid')
    test_dataset = KUAKE_Dataset(rawdata["test"], tokenizer, max_length=data_args.max_length, type_='test')

    # 使用自定义的 collate_fn 创建 DataLoader
    train_loader = DataLoader(train_dataset, batch_size=train_args.train_batch_size, shuffle=False,             
                            collate_fn=custom_collate_fn)
    valid_loader = DataLoader(valid_dataset, batch_size=train_args.eval_batch_size, shuffle=False,          
                             collate_fn=custom_collate_fn)
    test_loader = DataLoader(test_dataset, batch_size=train_args.eval_batch_size, shuffle=False,
                            collate_fn=custom_collate_fn)

    model = ContrastiveModel(data_args.model_dir, data_args.labels)
    model.to(train_args.device)

    print("Start training...")
    final_loss, final_steps = train_model(model, train_loader, valid_loader, train_args, tokenizer, writer)

    writer.close()
    print(f'Training Finished! Final Steps: {final_steps}, Final Loss: {final_loss}')

if __name__ == "__main__":
    args = args_parser()
    set_seed(42)
    main(args)




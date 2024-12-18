import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import optim
from torch.utils.data import DataLoader

import torchmetrics
import pytorch_lightning as pl
from pytorch_lightning.loggers import TensorBoardLogger
from pytorch_lightning.callbacks import LearningRateMonitor, ModelCheckpoint
from transformers import AutoTokenizer
from transformers.optimization import (
    get_linear_schedule_with_warmup,
    get_cosine_schedule_with_warmup,
    get_constant_schedule_with_warmup
)


from models.utils import *
from models.model import CustomRNNClassifier, RNNClassifier, TransformerClassifier
from dataloader.data import YelpDataset, collate_fn
from tqdm import tqdm

class TextClassifierLightning(pl.LightningModule):
    def __init__(self, train_config, model_config=None):
        super(TextClassifierLightning, self).__init__()

        if train_config.model == 'custom_rnn' or \
            train_config.model == 'custom_gru' or \
            train_config.model == 'custom_lstm':
            self.model = CustomRNNClassifier(model_config)
        elif train_config.model == 'rnn' or \
            train_config.model == 'lstm' or \
            train_config.model == 'gru':
            self.model = RNNClassifier(model_config)
        elif train_config.model == 'transformer':
            self.model = TransformerClassifier(model_config)
        else:
            raise ValueError(f"Unsupported model: {train_config.model}")
        self.train_config = train_config

        # Metrics
        self.train_acc = torchmetrics.Accuracy(task="multiclass", num_classes=model_config.output_dim)
        self.val_acc = torchmetrics.Accuracy(task="multiclass", num_classes=model_config.output_dim)
        self.test_acc = torchmetrics.Accuracy(task="multiclass", num_classes=model_config.output_dim)

        # Loss function
        self.criterion = nn.CrossEntropyLoss()

    def forward(self, input_ids, attention_mask=None):
        return self.model(input_ids, attention_mask)

    def training_step(self, batch, batch_idx):
        input_ids = batch['input_ids']
        attention_mask = batch['attention_mask']
        labels = batch['label']
        
        # Forward pass
        outputs = self(input_ids, attention_mask)  # outputs: logits
        loss = self.criterion(outputs, labels)

        # Update accuracy metric
        self.train_acc(outputs, labels)  # No need to process the outputs
        
        # Log metrics for each step
        if batch_idx % 50 == 0:
            self.log('train/loss', loss, on_step=True, on_epoch=False, prog_bar=True)
            self.log('train/acc', self.train_acc, on_step=True, on_epoch=False, prog_bar=True)
        
        return loss

    def validation_step(self, batch, batch_idx):
        input_ids = batch['input_ids']
        attention_mask = batch['attention_mask']
        labels = batch['label']
        
        # Forward pass
        outputs = self(input_ids, attention_mask)  # outputs: logits
        loss = self.criterion(outputs, labels)

        # Update accuracy metric
        self.val_acc(outputs, labels)

        # Log metrics for each step
        self.log('val/loss', loss, on_step=False, on_epoch=True)
        self.log('val/acc', self.val_acc, on_step=False, on_epoch=True)
        
    def test_step(self, batch, batch_idx):
        input_ids = batch['input_ids']
        attention_mask = batch['attention_mask']
        labels = batch['label']
        
        # Forward pass
        outputs = self(input_ids, attention_mask)  # outputs: logits
        loss = self.criterion(outputs, labels)

        # Update accuracy metric
        self.test_acc(outputs, labels)

        self.log('test/loss', loss, on_step=False, on_epoch=True)
        self.log('test/acc', self.test_acc, on_step=False, on_epoch=True)

    def configure_optimizers(self):
        if self.train_config.optimizer.lower() == 'adam':
            optimizer = optim.Adam(self.model.parameters(), lr=self.train_config.learning_rate, weight_decay=self.train_config.weight_decay)
        elif self.train_config.optimizer.lower() == 'sgd':
            optimizer = optim.SGD(self.model.parameters(), lr=self.train_config.learning_rate, weight_decay=self.train_config.weight_decay)
        else:
            raise ValueError(f"Unsupported optimizer: {self.train_config.optimizer}")

        # Set up the scheduler
        scheduler = None
        total_steps = self.train_config.total_steps

        warmup_steps = min(self.train_config.warmup_ratio * total_steps, 100)
        if self.train_config.scheduler.lower() == 'linear':
            scheduler = get_linear_schedule_with_warmup(
                optimizer,
                num_warmup_steps=warmup_steps,
                num_training_steps=total_steps
            )
        elif self.train_config.scheduler.lower() == 'cosine':
            scheduler = get_cosine_schedule_with_warmup(
                optimizer,
                num_warmup_steps=warmup_steps,
                num_training_steps=total_steps
            )
        elif self.train_config.scheduler.lower() == 'constant':
            scheduler = get_constant_schedule_with_warmup(
                optimizer,
                num_warmup_steps=warmup_steps
            )
        else:
            raise ValueError(f"Unsupported scheduler: {self.train_config.scheduler}")

        if scheduler:
            scheduler_config = {
                'scheduler': scheduler,
                'interval': 'step',  # or 'epoch'
                'frequency': 1
            }
            return [optimizer], [scheduler_config]
        else:
            return optimizer



def main():
    # Parse command-line arguments
    args = parse_args()
    # Create TrainConfig from parsed arguments
    train_config = TrainConfig(
        data_path=args.data_path,
        model=args.model,
        output_path=args.output_path,
        checkpoint_path=args.checkpoint,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        optimizer=args.optimizer,
        scheduler=args.scheduler,
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay
    )

    # Initialize tokenizer
    tokenizer = AutoTokenizer.from_pretrained('google-bert/bert-base-uncased')

    # Define ModelConfig, including vocab_size from tokenizer
    if train_config.model == 'rnn' or \
        train_config.model == 'custom_rnn':
        model_config = rnn_config
        model_config.pack = args.pack
    elif train_config.model == 'gru' or \
        train_config.model == 'custom_gru':
        model_config = gru_config
        model_config.pack = args.pack
    elif train_config.model == 'lstm' or \
        train_config.model == 'custom_lstm':
        model_config = lstm_config
        model_config.pack = args.pack
        model_config.bidirectional = args.bidirectional
    elif train_config.model == 'rcnn':
        model_config = rcnn_config
    elif train_config.model == 'rnn_attention':
        model_config = rnn_attention_config
    elif train_config.model == 'transformer':
        model_config = transformer_config
    else:
        raise ValueError(f"Unsupported model: {train_config.model}")
    
    model_config.vocab_size = tokenizer.vocab_size
    model_config.pool = args.pool
    model_config.output_dim = 5
    print("Model Config:")
    print(model_config)
    

    # Initialize datasets
    train_dataset = YelpDataset(
        data_dir=train_config.data_path,
        tokenizer=tokenizer,
        train=True,
        max_length=args.max_length,
        reload_=True
    )
    print(f"Number of training samples: {len(train_dataset)}")

    test_dataset = YelpDataset(
        data_dir=train_config.data_path,
        tokenizer=tokenizer,
        train=False,
        max_length=args.max_length,
        reload_=True
    )
    print(f"Number of test samples: {len(test_dataset)}")
    
    # Split training data into train and validation sets
    split_ratio = 0.8
    train_size = int(split_ratio * len(train_dataset))
    valid_size = len(train_dataset) - train_size
    train_subset, valid_subset = torch.utils.data.random_split(train_dataset, [train_size, valid_size])
    
    # Create DataLoaders
    train_loader = DataLoader(
        train_subset,
        batch_size=train_config.batch_size,
        shuffle=True,
        num_workers=4,
        persistent_workers=True,
        pin_memory=True,
        # collate_fn=collate_fn
    )
    valid_loader = DataLoader(
        valid_subset,
        batch_size=train_config.batch_size,
        shuffle=False,
        num_workers=4,
        persistent_workers=True,
        pin_memory=True,
        # collate_fn=collate_fn
    )
    
    test_loader = DataLoader(
        test_dataset,
        batch_size=train_config.batch_size,
        shuffle=False,
        num_workers=4,
        persistent_workers=True,
        # collate_fn=collate_fn
    )
    train_config.total_steps = len(train_loader) * train_config.epochs

    # TEST
    if train_config.model == 'custom_rnn' or \
        train_config.model == 'custom_gru' or \
        train_config.model == 'custom_lstm':
        model = CustomRNNClassifier(model_config)
    elif train_config.model == 'rnn' or \
        train_config.model == 'lstm' or \
        train_config.model == 'gru':
        model = RNNClassifier(model_config)
    elif train_config.model == 'rcnn':
        model = RCNNClassifier(model_config)
    elif train_config.model == 'rnn_attention':
        model = RNNAttentionClassifier(model_config)
    elif train_config.model == 'transformer':
        model = TransformerClassifier(model_config)
    else:
        raise ValueError(f"Unsupported model: {train_config.model}")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("Model Size:", sum(p.numel() for p in model.parameters() if p.requires_grad)//1e6, "M Parameters")

    model.to(device)

    optimizer = optim.Adam(model.parameters(), lr=train_config.learning_rate, weight_decay=train_config.weight_decay)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=100,
        num_training_steps=train_config.total_steps
    )
    criterion = nn.CrossEntropyLoss()
    with tqdm(total=train_config.total_steps, desc="Training") as pbar:
        model.train()
        for epoch in range(train_config.epochs):
            for batch in train_loader:
                pbar.update(1)
                optimizer.zero_grad()
                input_ids = batch['input_ids'].to(device)
                attention_mask = batch['attention_mask']
                attention_mask = attention_mask.to(device) if attention_mask is not None else None
                labels = batch['label'].to(device)
                outputs = model(input_ids, attention_mask)
                loss = criterion(outputs, labels)
                loss.backward()
                optimizer.step()
                scheduler.step()
                pbar.set_postfix({'loss': loss.item()})
                
    print("Training finished.")
    
    def accuracy(outputs, labels):
        _, preds = torch.max(outputs, dim=1)
        return torch.sum(preds == labels).item() / len(labels)
    valid_acc = 0
    valid_loss = 0
    with torch.no_grad():
        with tqdm(total=len(valid_loader), desc="Validation") as pbar:
            model.eval()
            for batch in valid_loader:
                pbar.update(1)
                input_ids = batch['input_ids'].to(device)
                attention_mask = batch['attention_mask']
                attention_mask = attention_mask.to(device) if attention_mask is not None else None
                labels = batch['label'].to(device)
                outputs = model(input_ids, attention_mask)
                loss = criterion(outputs, labels)
                valid_loss += loss.item()
                valid_acc += accuracy(outputs, labels)
    valid_loss /= len(valid_loader)
    valid_acc /= len(valid_loader)
    print(f"Validation Loss: {valid_loss:.4f}, Validation Accuracy: {valid_acc:.4f}")
    print("Validation finished.")

    test_acc = 0
    test_loss = 0
    with torch.no_grad():
        with tqdm(total=len(test_loader), desc="Testing") as pbar:
            model.eval()
            for batch in test_loader:
                pbar.update(1)
                input_ids = batch['input_ids'].to(device)
                attention_mask = batch['attention_mask']
                attention_mask = attention_mask.to(device) if attention_mask is not None else None
                labels = batch['label'].to(device)
                outputs = model(input_ids, attention_mask)
                loss = criterion(outputs, labels)
                test_loss += loss.item()
                test_acc += accuracy(outputs, labels)

    test_loss /= len(test_loader)
    test_acc /= len(test_loader)
    print(f"Test Loss: {test_loss:.4f}, Test Accuracy: {test_acc:.4f}")
    print("Testing finished.")



    # # Initialize the Lightning module
    # lightning_model = TextClassifierLightning(train_config=train_config, model_config=model_config)

    # # Set up model checkpointing to save the best model based on validation accuracy

    # timenow = time.strftime("%Y%m%d-%H-%M")
    # output_dir = os.path.join(train_config.output_path, train_config.model, timenow)
    # os.makedirs(output_dir, exist_ok=True)

    # checkpoint_callback = ModelCheckpoint(
    #     dirpath=output_dir,
    #     monitor="val/acc",
    #     mode="max",
    #     save_top_k=1,
    #     verbose=True,
    #     filename="best-checkpoint"
    # )

    # lr_monitor = LearningRateMonitor(logging_interval='step')

    # # Initialize PyTorch Lightning Trainer

    # logger = TensorBoardLogger("logs", name=train_config.model)

    # trainer = pl.Trainer(
    #     logger=logger,
    #     max_epochs=train_config.epochs,
    #     accelerator="gpu",
    #     callbacks=[checkpoint_callback, lr_monitor],
    #     val_check_interval=0.5,
    # )

    # # Train the model
    # print("Training the model...")
    # trainer.fit(lightning_model, train_loader, valid_loader)
    # print("Training finished.")

    # best_model_path = os.path.join(output_dir, "best-checkpoint.ckpt")

    # # # Load the best checkpoint for testing
    # # lightning_model = TextClassifierLightning.load_from_checkpoint(
    # #             checkpoint_path=checkpoint_callback.best_model_path,
    # #             model_config=model_config,
    # #             train_config=train_config
    # # )

    # # Test the model
    # print("Testing the model...")
    # trainer.test(lightning_model, dataloaders=test_loader)

if __name__ == "__main__":
    main()
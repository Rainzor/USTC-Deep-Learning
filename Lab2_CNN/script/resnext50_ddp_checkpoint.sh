torchrun --nproc_per_node=3  ./train_ddp.py -m 'resnext50' -d '/data2/wrz/Datasets/tiny-imagenet-200' -opt 'sgd' -lr 0.05 -o 'out' --momentum 0.9 --weight-decay 1e-4 --lr-scheduler 'cosine' --lr-warmup-epochs 5 --lr-warmup-method 'linear' --lr-warmup-decay 0.01 --writer --checkpoint ./out/resnext50/2024_12_09_04_44_ddp_model.pth -b 128 -n 100
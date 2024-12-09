torchrun --nproc_per_node=4  ./train_ddp.py -m 'vgg19' -d '/data2/wrz/Datasets/tiny-imagenet-200' -b 256 -n 200 -opt 'adam' -lr 5e-4 -o 'out'  --weight-decay 1e-4 --lr-scheduler 'cosine' --lr-warmup-epochs 5 --lr-warmup-method 'linear' --lr-warmup-decay 0.01 --writer --wo-norm
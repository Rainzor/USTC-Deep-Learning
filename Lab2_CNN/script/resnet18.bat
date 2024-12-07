python .\train.py ^
    -m "resnet18" ^
    -i "..\data\tiny-imagenet-200" ^
    -b 256 ^
    -n 50 ^
    -opt "sgd" ^
    -lr 0.2 ^
    -o "out" ^
    --momentum 0.9 ^
    --weight-decay 1e-4 ^
    --lr-scheduler "cosine" ^
    --lr-warmup-epochs 5 ^
    --lr-warmup-method "linear" ^
    --lr-warmup-decay 0.01

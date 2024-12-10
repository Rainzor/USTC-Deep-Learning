torchrun --nproc_per_node=3  ./train_ddp.py -m 't2t_vit_t_14' -d '/data2/wrz/Datasets/tiny-imagenet-200' -opt 'sgd'  -lr 0.05 -o 'out' --momentum 0.9 --weight-decay 1e-4 --lr-scheduler 'cosine' --writer --val 0.05  --checkpoint ./out/t2t_vit_t_14/2024_12_10_21_29_ddp_model.pth -b 128 -n 100
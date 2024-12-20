# Lab2: Convolution Neural Network

> 卷积神经网络：图像分类
>

## 1. Overview

使用 `pytorch` 实现卷积神经网络，在 ImageNet 数据集上进行图片分类。研究 dropout, normalization, learning rate decay, residual connection, network depth等超参数对分类性能的影响。

实验测试和对比的网络架构：

- `VGG`: [Very Deep Convolutional Networks for Large-Scale Image Recognition](https://arxiv.org/abs/1409.1556)
- `ResNet`: [Deep Residual Learning for Image Recognition](https://arxiv.org/abs/1512.03385)
- `ResNeXt:` [Aggregated Residual Transformations for Deep Neural Networks](https://arxiv.org/abs/1611.05431)
- `T2T-ViT`: [Tokens-to-Token ViT: Training Vision Transformers From Scratch on ImageNet](https://openaccess.thecvf.com/content/ICCV2021/html/Yuan_Tokens-to-Token_ViT_Training_Vision_Transformers_From_Scratch_on_ImageNet_ICCV_2021_paper.html)

## 2. Experiment

### 2.0 Environment

本实验在 Linux/Windows 操作系统下进行，主要包含的库有：

- pytorch
- opencv
- numpy
- tqdm
- tensorboard

更多库见 `requirement.txt`

代码文件包含：

- `train.py` 和  `train_ddp.py`：分别用于单GPU训练和多GPU训练
- `dataset.py`：管理和加载数据
- `model/*` ：包含实验相关的网络架构 `VGG`、`ResNet` 、`ResNeXt`和 `T2T_ViT`
- `utils.py`：其他的函数

## 2.1 Dataset

实验使用 [`Tiny-Imagenet-200` ](http://cs231n.stanford.edu/tiny-imagenet-200.zip) 数据集，包含 200 个类，每个类有 500 张训练图像，50 张验证图像和 50 张测试图像。由于测试图像没有标签，因此使用数据集中的 `val` 当作测试集，并从 `train` 中手动划分新的训练集和验证集。本实验采用 `val_ratio=0.2` 比例划分数据。

### 2.1.1 Load and preprocess

在 `dataset.txt` 中按照如下方式创建数据集，值得说明的是为了避免多次处理和加载数据，采用了 **文件Cache** 的方式保存图像和标签数据，保存在 `data_path/process` 目录下。

```python
class TinyImageNetDataset(Dataset):
    def __init__(self, type_, raw_data, transform=None, force_reload=False):
        """
        type_: 'train' or 'val'
        raw_data: RawData instance
        transform: torchvision transforms to apply
        force_reload: If True, ignore cached data and reprocess
        """
        self.type = type_
        self.raw_data = raw_data
        self.force_reload = force_reload

        # Create a directory to save processed data
        self.processed_path = os.path.join(self.raw_data.data_path, "process")
        os.makedirs(self.processed_path, exist_ok=True)

        # Load or preprocess data
        if self.type == "train":
            self.images, self.labels = self._load_or_preprocess_train_data()
        else:
            self.images, self.labels = self._load_or_preprocess_val_data()

        self.transform = transforms.ToTensor() if transform is None else transform
        ......
    def __getitem__(self, index):
        label = self.labels[index]
        image = self.images[index]
        return self.transform(image), label

    def __len__(self):
        return len(self.labels)
```

### 2.1.2 Data Argument

为了高效利用图像数据，对训练数据进行相关变换操作，用于数据增强。

```python
normalize = transforms.Normalize(mean=[0.4802, 0.4481, 0.3975],
                                     std=[0.2302, 0.2265, 0.2262])
train_transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.RandomResizedCrop(64),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalize])
test_transform = transforms.Compose([
                           transforms.ToTensor(),
                            normalize])
```

### 2.2 Models

### 2.2.1 VGG

对于CV领域，`VGG`是最早提出使用模块 (Block) 的形式来设计网络架构，之后经典卷积神经网络的基本组成部分是下面的这个序列：

1. 带 padding 以保持分辨率的卷积层；
2. 非线性激活函数，如ReLU；
3. Pooling，如最大汇聚层

```python
def vgg_block(num_convs, in_channels, out_channels, use_norm=True):
    layers = []
    for _ in range(num_convs):
        layers.append(nn.Conv2d(in_channels, out_channels,
                                kernel_size=3, padding=1))
        if use_norm:
            layers.append(nn.BatchNorm2d(out_channels))
        layers.append(nn.ReLU())
        in_channels = out_channels
    layers.append(nn.MaxPool2d(kernel_size=2,stride=2))
    return nn.Sequential(*layers)
```



<center class="half">
<img src="assets/image-20241208235931241.png" style="zoom: 33%;" />
<img src="assets/image-20241209000331936.png" style="zoom: 25%;" />
</center>
****

**实验主要测试了：** BatchNorm 的效果，主要模型为：

- 含BatchNorm:  `VGG19`，包含 16 个卷积层和 3 个全连接层
- 不含BatchNorm：`VGG19 (W/O BN)`

其中，HyperParameter:

- Epochs: 200

- Optimizer: `Adam`
- Schedular: `CosineAnnealingLR`
- Learning Rate: 5e-4
- Batch Size: 256

> 为什么需要批量规范化层呢？让我们来回顾一下训练神经网络时出现的一些实际挑战。
>
> 首先，数据预处理的方式通常会对最终结果产生巨大影响。 回想一下我们应用多层感知机来预测房价的例子。 使用真实数据时，我们的第一步是标准化输入特征，使其平均值为0，方差为1。 直观地说，这种标准化可以很好地与我们的优化器配合使用，因为它可以将参数的量级进行统一。
>
> 第二，对于典型的多层感知机或卷积神经网络。当我们训练时，中间层中的变量（例如，多层感知机中的仿射变换输出）可能具有更广的变化范围：不论是沿着从输入到输出的层，跨同一层中的单元，或是随着时间的推移，模型参数的随着训练更新变幻莫测。 批量规范化的发明者非正式地假设，这些变量分布中的这种偏移可能会阻碍网络的收敛。 直观地说，我们可能会猜想，如果一个层的可变值是另一层的100倍，这可能需要对学习率进行补偿调整。
>
> 第三，更深层的网络很复杂，容易过拟合。 这意味着正则化变得更加重要。
>
> 总之，在模型训练过程中，批量规范化利用小批量的均值和标准差，不断调整神经网络的中间输出，使整个神经网络各层的中间输出值更加稳定。

****

### 2.2.2 ResNet

残差神经网络的主要贡献是发现了“退化现象（Degradation）”，并针对退化现象发明了 “快捷连接（Shortcut connection）”，极大的消除了深度过大的神经网络训练困难问题。神经网络的“深度”首次突破了100层、最大的神经网络甚至超过了1000层。

具体来说，随着网络的深度变得越来越深。理论上，增加网络的深度应该能够提高模型的表现，因为更深的网络能够捕捉到更多的复杂特征。然而，随着网络深度的增加，实际训练中常常遇到以下问题：

1. **梯度消失与梯度爆炸**：在深度网络中，梯度在反向传播时容易变得非常小（梯度消失）或非常大（梯度爆炸），这使得模型难以训练。
2. **退化问题**：随着层数的增加，理论上模型的性能应该逐渐提升，但实际上，实验中发现随着网络层数的增加，训练误差反而增大，这称为退化问题（Degradation Problem）。

ResNet 的核心创新是引入了**残差块**（Residual Block），通过引入跳跃连接（Skip Connections）来解决深层网络训练中的问题。具体来说，残差块通过在每一层的输入和输出之间添加恒等映射来建立连接。这使得网络能够直接学习到输入和输出之间的**残差**，而不是直接学习复杂的映射。

**残差连接的形式：**

- 在每个残差块中，输入 $x$ 会通过一系列卷积层进行处理，产生输出 $F(x)$。
- 然后，输入 $x$ 会直接与输出 $F(x$) 相加，形成 $F(x)+x$，这个新的结果会传递到下一层。
- 这样，网络的目标就变成了学习输入与输出之间的**残差**，而不是直接学习复杂的映射。

这种设计可以通过使得梯度在反向传播时更容易流动，从而缓解梯度消失和梯度爆炸问题，同时避免了退化问题。

>  对于深度神经网络，如果我们能将新添加的层训练成*恒等映射*（identity function）$f(x)=x$，新模型和原模型将同样有效。 同时，由于新模型可能得出更优的解来拟合训练数据集，因此添加层似乎更容易降低训练误差。

```python
class ResBlock(nn.Module):    
    def __init__(self, in_channels, out_channels, stride = 1):
        super().__init__()            
        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size = 3, 
                               stride = stride, padding = 1)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size = 3, 
                               stride = 1, padding = 1)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace = True)
        if in_channels != out_channels:
            self.shortcut = nn.Sequential(
            				nn.Conv2d(in_channels, out_channels, kernel_size = 1, stride = stride),
            				nn.BatchNorm2d(out_channels))
        else:
            self.shortcut = nn.Identity()       
        
    def forward(self, x):
        i = x
        
        x = self.conv1(x)
        x = self.bn1(x)       
        x = self.relu(x)
        
        x = self.bn2(self.conv2(x))  
        x += self.shortcut(i)
        x = self.relu(x)       
        return x
```

<img src="assets/image-20241209003911334.png" alt="image-20241209003911334" style="zoom:50%;" />

****

**实验主要从两个方面来对比测试**： 

网络深度的变化和 Skip Connections

- Depth：对比经典的 `ResNet18`、`ResNet34`、`ResNet50`
- Skip Connections：删去 `ResNet50` 中的残差连接

**HyperParameter**:

- Epochs: 100
- Optimizer: `SGD`
- Momentum: 0.9
- Schedular: `CosineAnnealingLR`
- Learning Rate: 0.2
- Batch Size: 256

**值得强调的是：** 

由于 `TinyImageNet` 图像是 $64\times64$ 的，所以在原来 ResNet的基础上将最开始 **Block** 改为 $3\times 3$ 的卷积核。

```python
# Different from origin ResNet, we use kernel_size=3, stride=1
self.conv1 = nn.Conv2d(3, self.in_channels, kernel_size=3, stride=1, 
                       padding=1, bias=False)
#self.conv1 = nn.Conv2d(3, self.in_channels, kernel_size=7, stride=3, 
#                       padding=3, bias=False)
self.bn1 = nn.BatchNorm2d(self.in_channels)
self.relu = nn.ReLU(inplace=True)
# self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
self.maxpool = nn.Identity()
```



### 2.2.3 ResNeXt

ResNeXt 是一种改进的卷积神经网络架构，它是在 ResNet 的基础上进行扩展和优化的。ResNeXt 的设计理念是基于“分组卷积”（Group Convolution）来提高网络的表现力，同时保持计算效率和模型的可扩展性。

深度卷积神经网络（如 ResNet）在图像分类、目标检测、语义分割等任务中取得了非常好的效果，但它们通常面临以下挑战：

1. **深度网络的训练**：尽管增加网络深度通常能提高性能，但也会带来训练难度，尤其是在计算资源有限的情况下。
2. **参数数量过大**：为了提高网络表现力，增加了网络的宽度和深度，但这也会导致模型参数数量和计算量的爆炸性增长。

除了网络深度和网络宽度以外，ResNeXt 注意到 **Cardinality** 这个维度，具体来说：

- ResNeXt 将 Channel 进行分组，**Cardinality** 是指分组卷积中“Group的数量”
- 然后，每个Group会单独进行卷积运算，这使得每个卷积核只作用于输入的一部分通道,
- 最后将结果拼接起来。

<img src="assets/image-20241209201952880.png" alt="image-20241209201952880" style="zoom:33%;" />

如图所示，在参数量相同的前提下，左边是ResNet，右边是ResNeXt，ResNeXt的主要区别在于对各个通道进行独立的卷积运算。

****

实验主要对比：**在总参数量大致相同的前提下，进行分组卷积后进行测试**。

**HyperParameter**:

- Epochs: 100
- Optimizer: `SGD`
- Momentum: 0.9
- Schedular: `CosineAnnealingLR`
- Learning Rate: 0.1
- Batch Size: 128
- cardinality: 32
- base_width: 4

### 2.2.4 ViT

**Vision Transformer (ViT)** 是一种基于 Transformer 架构的图像分类模型，它通过将图像视为一个由小块（patch）组成的序列，借助 Transformer 进行处理，标志着从传统的卷积神经网络（CNN）到基于 Transformer 的模型在CV领域中的一次重要转变。

ViT 通过将图像划分为固定大小的块（patch），并将这些块作为一个序列输入到 Transformer 中，完全摒弃了传统 CNN 中的卷积层。这种方法成功地将 Transformer 引入到图像分类任务中

Transformer架构的核心部件在于：Attention Mechanics，允许模型在处理每个图像块时考虑其他所有块的信息，而不是像 CNN 那样仅依赖局部感受野。这使得 ViT 能够捕捉到全局上下文信息，并能更好地处理复杂的图像特征。

<img src="assets/image-20241209203454625.png" alt="image-20241209203454625" style="zoom:33%;" />

**某种意义上，Multi-Head Attention 正是承袭了 ResNeXt 的思路，将特征进行分组处理，更加高效地捕捉到数据中的重要特征。**

****

由于ViT模型是依赖于大量数据和算力训练的预训练模型，所以本实验采用了可以重头训练的模型 **T2T ViT**。在原来 ViT的基础上，添加了 **Token-to-Token** 模块，强调对图像进行分割时，需要存在部分重叠，使得 Patch 之间更容易提取彼此间的特征。

<img src="assets/image-20241209204214281.png" alt="image-20241209204214281" style="zoom: 33%;" />

## 3. Results

### 3.1 VGG

在VGG的实验中，主要对比了**Batch Norm**的效果，如下图所示

<img src="assets/image-20241209212438055.png" alt="image-20241209212438055" style="zoom: 50%;" />

图中对坐标轴进行的调整方便对比，可以看到在相同超参数前提下，未添加 **Batch Norm** 训练时损失难以下降，且验证集曲线没有收敛。这证明了Batch Norm 对于数值稳定和网络最终收敛性的作用。

最终在 Test Dataset 上 **Top-1 Accuracy** 为：

- VGG：0.5279
- VGG (Without BatchNorm): 0.0050

### 3.2 ResNet

首先对比了不同 **Depth** 对于ResNet的提升，主要是 `ResNet18`, `ResNet34` 和 `ResNet50`

<img src="assets/image-20241210190721219.png" alt="image-20241210190721219" style="zoom:50%;" />

可以看到 **Depth** 的增加可以提高网络最终收敛的结果。

接着对比了 **Skip Connect**ion 对于 `ResNet50` 的影响，为了比较公平性，对比了相同参数量的 `ResNet34`

<img src="assets/image-20241210190736867.png" alt="image-20241210190736867" style="zoom:50%;" />

同样的，**Skip Connection** 对于收敛性和图像分类提升有帮助。

最终在 Test Dataset 上 **Top-1 Accuracy** 为：

- `ResNet18` Acc: 0.5509, Param: 11.27M
- `ResNet34` Acc: 0.5603, Param: 21.38M
- `ResNet50` Acc:0.5897, Param: 23.91M
- `ResNet50 (W/O Skip)` Acc: 0.5403, Param: 21.133M

### 3.3 ResNeXt

ResNeXt对比 ResNet 添加了**Cardinality** 维度，实验在相同参数量下，对比了 `ResNet50` 和 `ResNeXt50` 的结果

<img src="assets/image-20241210190804910.png" alt="image-20241210190804910" style="zoom:50%;" />

可以看到，ResNeXt 收敛的更快。

最终在 Test Dataset 上 **Top-1 Accuracy** 为：

- `ResNet50`  Acc: 0.5897, Param: 23.91M
- `ResNeXt50` Acc: 0.5929, Param: 23.38M

### 3.4 ViT

在 **Tiny ImageNet** 训练 **T2T ViT** 的结果和 **ResNeXt** 对比结果如下

<img src="assets/image-20241215144502821.png" alt="image-20241215144502821" style="zoom: 50%;" />

可以看到最终ViT结果虽然收敛更好，但是在验证集上存在严重过拟合的问题，这可能是由于  `TinyImageNet` 的训练数据量不足导致的，故而最终的结果为：

- `ResNeXt50` Acc: 0.5929, Param: 23.38M
- `T2T-ViT-T-14` Acc: 0.4163, Param: 21.23M

## 4. Conclusion

在本次实验中，我们深入研究并比较了多种卷积神经网络（CNN）架构在 **Tiny ImageNet-200** 数据集上的图像分类性能。通过对 `VGG`、`ResNet`、`ResNeXt` 以及 `T2T-ViT` 等模型的实现与测试，我们系统地分析了不同架构及其超参数对分类效果的影响。

### 4.1 Batch Normalization 的重要性

在 **VGG** 模型的实验中，我们观察到 **Batch Normalization (BatchNorm)** 对模型训练的显著影响。含有 BatchNorm 的 `VGG19` 模型在训练过程中损失迅速下降并在验证集上取得了较高的准确率（52.79%），而未添加 BatchNorm 的版本则表现极差（0.50%）。这一结果验证了 BatchNorm 在稳定训练过程、加速收敛以及提高模型泛化能力方面的重要作用。

### 4.2 网络深度与残差连接的效果

通过对不同深度的 **ResNet** 模型（`ResNet18`、`ResNet34` 和 `ResNet50`）的比较，我们发现随着网络深度的增加，模型的分类准确率也相应提升，`ResNet50` 达到了最高的 **Top-1 Accuracy**（58.97%）。此外，移除 **Skip Connections** 后的 `ResNet50` 显著下降至 54.03%，进一步证明了残差连接在缓解梯度消失、提升深层网络训练效果中的关键作用。

### 4.3 ResNeXt 的优化优势

在 **ResNeXt** 的实验中，通过引入 **Cardinality**（分组卷积），在保持相近参数量的情况下，`ResNeXt50` 相较于 `ResNet50` 实现了略微提升的准确率（59.29% 对比 58.97%），且收敛速度更快。这表明 ResNeXt 通过增加分组数，有效增强了模型的表示能力，同时保持了计算效率，是对 ResNet 的有效优化。

### 4.4 Vision Transformer 的局限性

尽管 **T2T-ViT** 作为一种基于 Transformer 的图像分类模型，在理论上具备强大的全局特征捕捉能力，但在本次实验中，其在 **Tiny ImageNet** 数据集上的表现（**Top-1 Accuracy** 为 39.48%）明显低于基于 CNN 的 ResNeXt 模型。这主要归因于 **Tiny ImageNet** 数据集规模相对较小，无法充分发挥 ViT 模型对大规模数据和算力的需求，导致模型在训练过程中出现严重的过拟合现象。

### 4.5 总结与展望

本次实验系统地展示了不同 CNN 架构在图像分类任务中的性能表现，并强调了关键技术如 BatchNorm、残差连接以及分组卷积在提升模型效果中的重要性。具体结论如下：

1. **Batch Normalization** 是提升模型稳定性和收敛速度的关键组件，几乎在所有深度学习模型中都表现出其不可或缺的价值。
2. **网络深度** 与 **残差连接** 共同作用，显著提升了深层网络的训练效果和分类准确率。
3. **分组卷积（Cardinality）** 的引入在保持模型参数量的同时，进一步增强了模型的表现力，是 ResNeXt 相较于 ResNet 的一大优势。
4. **Vision Transformer** 在小规模数据集上的表现仍有待提升，未来研究可考虑结合 CNN 的局部特征提取优势，或在更大规模的数据集上验证其潜力。

未来可以进一步探索以下方向：

- **混合模型架构**：结合 CNN 和 Transformer 的优势，设计更为高效和强大的图像分类模型。
- **数据增强与正则化技术**：针对过拟合问题，进一步优化数据增强策略和正则化方法，以提升模型的泛化能力。
- **超参数优化**：系统地调整和优化各类超参数（如学习率、Batch Size 等），以挖掘模型潜力，提升分类性能。
- **扩展到更大规模的数据集**：在更大且多样化的数据集上验证模型的有效性和鲁棒性，确保其在实际应用中的适用性。

通过本次实验，我们不仅加深了对不同深度学习模型的理解，也为未来的模型设计和优化提供了有价值的参考。

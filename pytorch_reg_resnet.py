import torch
import torchvision
import numpy as np
import torch.nn as nn
import torch.optim as optim
import time
from dataset import load_data
from torch.utils.data import Dataset
from resnet import resnet18, resnet34, resnet50
import torch.backends.cudnn as cudnn
from averagemeter import AverageMeter
from pytorch_lgm_loss import LGMLoss
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--batchsize", type=int, default=8)
parser.add_argument("--epoch", type=int, default=400)
parser.add_argument("--opt", type=str, default='no')
parser.add_argument("--model", type=str, default='resnet18')
parser.add_argument("--mean", type=str, default='false')
parser.add_argument("--weight_decay", type=float, default=0.0001)
parser.add_argument("--lr", type=float, default=0.01)
parser.add_argument("--mom", type=float, default=0.9)
parser.add_argument("--mean_weight_decay", type=float, default=0.0001)
parser.add_argument("--mean_lr", type=float, default=0.01)
parser.add_argument("--mean_mom", type=float, default=0.9)
parser.add_argument("--feat_dim", type=int, default=12)
parser.add_argument("--print_freq", type=int, default=1)
args = parser.parse_args()


def one_hot(y):
    #if torch.cuda.is_available():
     #   y = y.cuda()

    y_onehot = torch.zeros(y.size()[0], 12).scatter_(1, y.view(y.size()[0], 1), 1)
    #print('y_onehot: {}'.format(y_onehot))
    return y_onehot

def torch_preprocess_input(x):
    x = x.astype(np.float32)
    x /= 255.
    x -= 0.5
    x *= 2.
    images = np.array(x)
    x = np.transpose(images, (0, 3, 1, 2))

    return x

class ProteinDataset(Dataset):
    def __init__(self, type):
        self.x, self.y = load_data(type)
        self.x = torch_preprocess_input(self.x)
        self.y = np.array(self.y)
        self.size = len(self.x)
        print(self.x.shape, self.y.shape)


    def __len__(self):
        return self.size

    def __getitem__(self, item):
        result = (self.x[item, ], self.y[item, ])
        return result


def accuracy(output, target):
    total = 0
    correct = 0
    with torch.no_grad():
        _, predicted = torch.max(output.data, 1)
        total += target.size(0)
        correct += (predicted == target).sum().item()
    percent_acc = 100 * correct/total
    return percent_acc


def train_epoch(data_loader, model, criterion, optimizer, mean_optimizer=None, _WEIGHT_DECAY = 5e-4, print_freq=args.print_freq):
    losses = AverageMeter()
    percent_acc = AverageMeter()
    means_param = AverageMeter()
    model.train()
    time_now = time.time()

    for batch_idx, (data, target) in enumerate(data_loader):
        target = target.long()
        target_backup = target
        if torch.cuda.is_available():
            data = data.cuda()
            target = target.cuda()
        #print('target: {}'.format(target))
        #print('onehot_target: {}'.format(one_hot(target)))
        output = model(data)
        #print("output.shape: {}".format(output.shape))
        ################## main parts of lgm loss
        loss = criterion(output, target)
        ################## main parts of lgm loss


        losses.update(loss.item(), data.size(0))

        acc = accuracy(output, target)
        percent_acc.update(acc, data.size(0))

        # compute gradient and do SGD step
        #means_param.update(means.item(), data.size(0))

        if args.mean == 'true':
            mean_optimizer.zero_grad()

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if args.mean == 'true':
            mean_optimizer.step()
        time_end = time.time() - time_now
        if batch_idx % print_freq == 0:
            print('Training Round: {}, Time: {}'.format(batch_idx, np.round(time_end, 2)))
            print('loss: {}'.format(loss))
    return losses, percent_acc


def validate(val_loader, model, criterion, _WEIGHT_DECAY = 5e-4, print_freq=10000):
    model.eval()
    losses = AverageMeter()
    percent_acc = AverageMeter()
    with torch.no_grad():
        time_now = time.time()
        for batch_idx, (data, target) in enumerate(val_loader):
            target = target.long()
            target_backup = target
            if torch.cuda.is_available():
                data = data.cuda()
                target = target.cuda()

            output = model(data)
            # print("output.shape: {}".format(output.shape))
            ################## main parts of lgm loss
            loss = criterion(output, target)
            ################## main parts of lgm loss

            ################## l2 regularization loss for loss
            losses.update(loss.item(), data.size(0))

            acc = accuracy(output, target)
            percent_acc.update(acc, data.size(0))

            time_end = time.time() - time_now
            """
            if batch_idx % print_freq == 0:
                print('Validation Round: {}, Time: {}'.format(batch_idx, np.round(time_end, 2)))
                print('Validation Loss: val:{} avg:{} Acc: val:{} avg:{}'.format(losses.val, losses.avg,
                                                                      percent_acc.val, percent_acc.avg))
                                                                      """
    return losses, percent_acc



def main():
    if torch.cuda.is_available():
        cudnn.benchmark = True
    batch_size = args.batchsize

    workers = 4
    global best_val_acc, best_test_acc

    if args.model == 'resnet18':
        model = resnet18(12)
    if args.model == 'resnet34':
        model = resnet34(12)
    if args.model == 'resnet50':
        model = resnet50(12)
    #if Config.gpu is not None:
    if torch.cuda.is_available():
        model = model.cuda()


    criterion = torch.nn.CrossEntropyLoss().cuda()
    if torch.cuda.is_available():
        criterion = criterion.cuda()
    if args.opt == 'adam':
        optimizer = torch.optim.Adam(model.parameters())
    else:
        optimizer = torch.optim.SGD(model.parameters(),
                                    lr=args.lr, momentum=args.mom,nesterov=True, weight_decay=args.weight_decay)

    train_dataset = ProteinDataset('train')
    val_dataset = ProteinDataset('val')
    #print("train_dataset.shape: {}, val_dataset.shape: {}".format(train_dataset.shape, val_dataset.shape))
    train_loader = torch.utils.data.DataLoader(train_dataset,
                              batch_size=batch_size, shuffle=True, pin_memory=True,
                              num_workers=workers)
    val_loader = torch.utils.data.DataLoader(val_dataset,
                            batch_size=batch_size, shuffle=True, pin_memory=True,
                            num_workers=workers)

    best_val_acc = 0
    for epoch in range(args.epoch):
        train_losses, train_acc = train_epoch(train_loader, model, criterion, optimizer)
        print('Epoch: {} train loss: {}, train acc: {}'.format(epoch, train_losses.avg, train_acc.avg))

        val_losses, val_acc = validate(val_loader, model, criterion)
        is_best = val_acc.avg > best_val_acc
        if is_best:
            best_val_acc = val_acc.avg
        print('>>>>>>>>>>>>>>>>>>>>>>')
        print('Epoch: {} train loss: {}, train acc: {}, valid loss: {}, valid acc: {}'.format(epoch, train_losses.avg, train_acc.avg,
                                                                                    val_losses.avg, val_acc.avg))
        print('Is this best? {}'.format(is_best))

        print('>>>>>>>>>>>>>>>>>>>>>>')
        """
        save_checkpoint({'epoch': epoch + 1,
                         'state_dict': model.state_dict(),
                         'best_val_acc': best_val_acc,
                         'optimizer': optimizer.state_dict(),}, is_best)
                         """
    #_, test_acc = validate(test_loader, model, criterion)
    #print('Test accuracy: {}'.format(test_acc))


if __name__ == '__main__':
    main()
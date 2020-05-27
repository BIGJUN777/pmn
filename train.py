import os
import time
import argparse
from tqdm import tqdm

import torch
from torch import nn, optim
from torch.utils.data import DataLoader
from tensorboardX import SummaryWriter

from datasets.vcoco_constants import VcocoConstants
from datasets.vcoco_dataset import VcocoDataset, collate_fn
from model.pgception import PGception
import utils.io as io

###########################################################################################
#                                     TRAIN MODEL                                         #
###########################################################################################
def run_model(args, data_const):
    # prepare data
    train_dataset = VcocoDataset(data_const=data_const, subset="vcoco_train")
    val_dataset = VcocoDataset(data_const=data_const, subset="vcoco_val")
    dataset = {'train': train_dataset, 'val': val_dataset}

    train_dataloader = DataLoader(dataset=dataset['train'], batch_size=args.batch_size, shuffle=True, pin_memory=True, collate_fn=collate_fn)
    val_dataloader = DataLoader(dataset=dataset['val'], batch_size=args.batch_size, shuffle=True, pin_memory=True, collate_fn=collate_fn)
    dataloader = {'train': train_dataloader, 'val': val_dataloader}
    print("Preparing data done!!!")

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'training on {device}...')
    # [64,64,128,128], [128,256,256,256]
    model = PGception(action_num=args.a_n, layers=args.n_layers, classifier_mod=args.c_m, o_c_l=args.o_c_l, 
                      last_h_c=args.last_h_c, bias=args.bias, drop=args.d_p, bn=args.bn)
    # load pretrained model
    if args.pretrained:
        print(f"loading pretrained model {args.pretrained}")
        checkpoints = torch.load(args.pretrained, map_location=device)
        model.load_state_dict(checkpoints['state_dict'])
    model.to(device)
    # # build optimizer && criterion  
    if args.optim == 'sgd':
        optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=0.9, weight_decay=0)
    else:
        optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=0)
    criterion = nn.BCEWithLogitsLoss()
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=400, gamma=1/3) #the scheduler divides the lr by 10 every 150 epochs
    # set visualization and create folder to save checkpoints
    writer = SummaryWriter(log_dir=args.log_dir + '/' + args.exp_ver)
    io.mkdir_if_not_exists(os.path.join(args.save_dir, args.exp_ver), recursive=True)
    # start training
    for epoch in range(args.start_epoch, args.epoch):
        # each epoch has a training and validation step
        epoch_loss = 0
        for phase in ['train', 'val']:
            start_time = time.time()
            running_loss = 0
            # all_edge = 0
            idx = 0
            # import ipdb; ipdb.set_trace()
            for data in tqdm(dataloader[phase]):
                pose_feat = data["pose_feat"]
                labels = data['pose_labels']
                pose_feat, labels = pose_feat.to(device), labels.to(device)
                if phase == "train":
                    model.train()
                    model.zero_grad()
                    outputs = model(pose_feat)
                    loss = criterion(outputs, labels)
                    loss.backward()
                    optimizer.step()
                else:
                    model.eval()
                    with torch.no_grad():
                        outputs = model(pose_feat)
                        loss = criterion(outputs, labels)

                running_loss += loss.item() * labels.shape[0]

            epoch_loss = running_loss / len(dataset[phase])
            if phase == 'train':
                train_loss = epoch_loss 
            else:
                writer.add_scalars('trainval_loss_epoch', {'train': train_loss, 'val': epoch_loss}, epoch)
            # print data
            if (epoch % args.print_every) == 0:
                end_time = time.time()
                print("[{}] Epoch: {}/{} Loss: {} Execution time: {}".format(\
                        phase, epoch+1, args.epoch, epoch_loss, (end_time-start_time)))
                        
        # scheduler.step()
        # save model epoch_loss<0.29 or 
        if epoch % args.save_every == (args.save_every - 1) and epoch >= (400-1):
            checkpoint = { 
                            'lr': args.lr,
                           'b_s': args.batch_size,
                          'bias': args.bias, 
                            'bn': args.bn, 
                       'dropout': args.d_p,
                         'o_c_l': args.o_c_l,
                      'last_h_c': args.last_h_c,
                           'a_n': args.a_n,
                'classifier_mod': args.c_m,
                    'state_dict': model.state_dict()
            }
            save_name = "checkpoint_" + str(epoch+1) + '_epoch.pth'
            torch.save(checkpoint, os.path.join(args.save_dir, args.exp_ver, save_name))

    writer.close()
    print('Finishing training!')

###########################################################################################
#                                 SET SOME ARGUMENTS                                      #
###########################################################################################
# define a string2boolean type function for argparse
def str2bool(arg):
    arg = arg.lower()
    if arg in ['yes', 'true', '1']:
        return True
    elif arg in ['no', 'false', '0']:
        return False
    else:
        # raise argparse.ArgumentTypeError('Boolean value expected!')
        pass

parser = argparse.ArgumentParser(description="HOI DETECTION!")

parser.add_argument('--batch_size', '--b_s', type=int, default=32,
                    help='batch size: 1')
parser.add_argument('--lr', type=float, default=0.00003, 
                    help='learning rate: 0.001')
parser.add_argument('--d_p', type=float, default=0, 
                    help='dropout parameter: 0')
parser.add_argument('--bias', type=str2bool, default='true', 
                    help="add bias to fc layers or not: True")
parser.add_argument('--bn', type=str2bool, default='false', 
                    help='use batch normailzation or not: true')
parser.add_argument('--epoch', type=int, default=700,
                    help='number of epochs to train: 300') 
parser.add_argument('--o_c_l', type=list, default=[128,256,256,256],
                    help='out channel in each branch in PGception layer: [128,256,256,256]')
parser.add_argument('--last_h_c', type=int, default=512,
                    help='the channel of last hidden layer: 512') 
parser.add_argument('--start_epoch', type=int, default=0,
                    help='number of beginning epochs : 0') 
parser.add_argument('--c_m',  type=str, default="cat", choices=['cat', 'mean'],
                    help='the model of last classifier: cat or mean')
parser.add_argument('--optim',  type=str, default='sgd', choices=['sgd', 'adam'],
                    help='which optimizer to be use: sgd or adam')
parser.add_argument('--a_n',  type=int, default=24,
                    help='acition number: 24')
parser.add_argument('--n_layers', type=int, default=1,
                    help='number of inception blocks: 1')

parser.add_argument('--pretrained', '-p', type=str, default=None,
                    help='location of the pretrained model file for training: None')
parser.add_argument('--log_dir', type=str, default='./log/vcoco',
                    help='path to save the log data like loss\accuracy... : ./log') 
parser.add_argument('--save_dir', type=str, default='./checkpoints/vcoco',
                    help='path to save the checkpoints: ./checkpoints/vcoco')
parser.add_argument('--exp_ver', '--e_v', type=str, default='v1', 
                    help='the version of code, will create subdir in log/ && checkpoints/ ')

parser.add_argument('--print_every', type=int, default=10,
                    help='number of steps for printing training and validation loss: 10')
parser.add_argument('--save_every', type=int, default=20,
                    help='number of steps for saving the model parameters: 50') 

args = parser.parse_args() 

if __name__ == "__main__":
    data_const = VcocoConstants()
    run_model(args, data_const)

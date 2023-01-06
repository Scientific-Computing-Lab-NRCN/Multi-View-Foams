import os
import sys
from os.path import dirname, abspath

project_path = dirname(dirname(abspath(__file__)))
sys.path.append(project_path)
sys.path.append(os.path.join(project_path, 'model2'))

import time
import copy
import pdb
import pickle
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
from datetime import date
import numpy as np

from model2 import ObjectsDataset, MVCNN, model_dir_config, count_parameters
from config import preprocess_dir, verbose


models_names = ['bottom', 'top', 'top_bottom', 'multi_top_bottom', 'multi_all', 'multi_profiles']
# Examples type:
# Seperated:  X10_0 (bottom), X10_1 (top), X10_both
multiview_arr = ['all', 'X10', 'X20']
examples_types = [['X10_0', 'X10_0'], ['X10_1', 'X10_1'], ['X10_both', 'X10_both'], ['X10', 'X10'], ['all', 'all'], ['X20', 'X20']]

# ---Model settings---
fc_in_features = 128  # 64 / 128 / 256
EPOCHS = 150
num_workers = 8
# ---Model settings---

cur_date = date.today().strftime("%d_%m_%Y")
data_path = preprocess_dir  # directory of the data set after pre-process
base_train_test = True # if true use the base train to test split in data dir and not randomize
full_data_use = True  # if false use 20 examples less in train set
augmentation = True  # augmentation such as brightnesss adjustments and gaussian noise
rotation = True  # rotation augmentation

model_dir = model_dir_config(fc_in_features, cur_date, full_data_use)
try:
    os.mkdir(model_dir)
except:
    version = int(model_dir.split('_')[-1])
    model_dir = f'{model_dir}_{version + 1}' if version < 30 else f'{model_dir}_1'
    os.mkdir(f'{model_dir}')


def verbosity(examples_type, multiview, no_yellow, val_indices, train_indices, dataset, device):
    print('\ntraining...')
    print(f'device: {device}')
    print(f'Examples type: {examples_type} \nMultiview: {multiview}\nNo yellow: {no_yellow}\n')
    if verbose > 1:
        print(f'Val indices length: {len(val_indices)} \nTrain indices length: {len(train_indices)} \n')
    if verbose > 2:
        print(f'train group names: {np.array(dataset.group_names)[train_indices]} \ntest group names: {np.array(dataset.group_names)[val_indices]} \n')
        print(f'train group labels: {np.array(dataset.group_labels)[train_indices]} \ntest group labels: {np.array(dataset.group_labels)[val_indices]} \n')


def train_model(model, dataloaders, criterion, optimizer, num_epochs=25):
    since = time.time()

    train_acc_history = []
    train_loss_history = []
    val_acc_history = []
    val_loss_history = []
    best_model_wts = copy.deepcopy(model.state_dict())
    best_model_wts_loss = copy.deepcopy(model.state_dict())
    best_acc = 0.0
    best_loss = 100

    for epoch in range(1, num_epochs + 1):
        if verbose:
            print('Epoch {}/{}'.format(epoch, num_epochs))
            print('-' * 10)

        # Each epoch has a training and validation phase
        for phase in ['train', 'val']:
            if phase == 'train':
                model.train()  # Set model to training mode
            else:
                model.eval()  # Set model to evaluate mode

            running_loss = 0.0
            running_corrects = 0
            all_preds = []
            all_labels = []
            # Iterate over data.
            for inputs, labels in dataloaders[phase]:
                inputs = inputs.to(device)
                labels = labels.to(device)

                # zero the parameter gradients
                optimizer.zero_grad()

                # forward
                # track history if only in train
                with torch.set_grad_enabled(phase == 'train'):
                    # Get model outputs and calculate loss
                    outputs = model(inputs)
                    loss = criterion(outputs, labels)
                    # Get model predictions
                    _, preds = torch.max(outputs, 1)
                    # pdb.set_trace()
                    # backward + optimize only if in training phase
                    if phase == 'train':
                        loss.backward()
                        optimizer.step()

                # statistics
                running_loss += loss.item() * inputs.size(0)
                running_corrects += torch.sum(preds == labels.data)
                all_preds.append(preds)
                all_labels.append(labels)

            epoch_loss = running_loss / len(dataloaders[phase].sampler.indices)
            epoch_acc = running_corrects.double() / len(dataloaders[phase].sampler.indices)
            all_labels = torch.cat(all_labels, 0)

            if verbose:
                print('{} Loss: {:.4f} - Acc: {:.4f}'.format(phase, epoch_loss, epoch_acc))

            # deep copy the model
            if phase == 'val' and epoch_loss < best_loss:
                best_loss = epoch_loss
                best_acc_loss = epoch_acc
                best_model_wts_loss = copy.deepcopy(model.state_dict())
            if phase == 'val' and epoch_acc > best_acc:
                best_acc = epoch_acc
                best_model_wts = copy.deepcopy(model.state_dict())
            if phase == 'val':
                val_acc_history.append(epoch_acc)
                val_loss_history.append(epoch_loss)
            else:
                train_acc_history.append(epoch_acc)
                train_loss_history.append(epoch_loss)

    model.load_state_dict(best_model_wts)
    torch.save(model.state_dict(), os.path.join(save_dir, f'model_by_acc_{int(best_acc * 100)}.pt'))
    model.load_state_dict(best_model_wts_loss)
    torch.save(model.state_dict(), os.path.join(save_dir, f'model_by_loss_{int(best_acc_loss*100)}.pt'))

    time_elapsed = time.time() - since
    if verbose:
        print('Training complete in {:.0f}m {:.0f}s'.format(time_elapsed // 60, time_elapsed % 60))
        print('Best val Acc: {:4f}'.format(best_acc))
        print('Best val Acc by loss: {:4f}'.format(best_acc_loss))

    return model, val_acc_history, val_loss_history, train_acc_history, train_loss_history, best_acc


for i, model_name in enumerate(models_names):
    folder_dir = os.path.join(model_dir, f'{model_name}')
    os.mkdir(folder_dir)
    for j, examples_type in enumerate(examples_types[i]):
        save_dir = os.path.join(folder_dir, f'{examples_type}_{j}')
        os.mkdir(save_dir)
        no_yellow = False
        multiview = False
        if j == 1:
            no_yellow = True
        if examples_type in multiview_arr:
            multiview = True
        dataset = ObjectsDataset(data_path=data_path,
                                 multiview=multiview,
                                 augmentation=augmentation,
                                 rotation=rotation,
                                 examples_type=examples_type,
                                 no_yellow=no_yellow,
                                 save_dir=save_dir,
                                 full_data_use=full_data_use,
                                 base_train_test=base_train_test)
        group_names = dataset.group_names
        y = dataset.group_labels
        outer_group_names = dataset.outer_group_names
        train_indices, val_indices = dataset.dataExtract.train_test_split()
        train_sampler = SubsetRandomSampler(train_indices)
        val_sampler = SubsetRandomSampler(val_indices)

        train_loader = DataLoader(dataset, batch_size=4, sampler=train_sampler, num_workers=num_workers)
        val_loader = DataLoader(dataset, batch_size=4, sampler=val_sampler, num_workers=num_workers)
        data_loaders = {'train': train_loader, 'val': val_loader}

        model = MVCNN(fc_in_features=fc_in_features, pretrained=True)

        # DEFINE THE DEVICE
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        model.to(device)
        if verbose:
            verbosity(examples_type, multiview, no_yellow, val_indices, train_indices, dataset, device)


        # UNFREEZE ALL THE WEIGHTS OF THE NETWORK
        for param in model.parameters():
            param.requires_grad = True
        # FINE-TUNE THE ENTIRE MODEL (I.E FEATURE EXTRACTOR + CLASSIFIER BLOCKS) USING A VERY SMALL LEARNING RATE
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=0.00005)  # We use a smaller learning rate

        model, val_acc_history, val_loss_history, train_acc_history, train_loss_history, best_acc = train_model(model=model, dataloaders=data_loaders, criterion=criterion, optimizer=optimizer, num_epochs=EPOCHS)
        with open(os.path.join(save_dir, 'val_acc_history.pkl'), 'wb') as f:
            pickle.dump(val_acc_history, f)
        with open(os.path.join(save_dir, 'val_loss_history.pkl'), 'wb') as f:
            pickle.dump(val_loss_history, f)
        with open(os.path.join(save_dir, 'train_acc_history.pkl'), 'wb') as f:
            pickle.dump(train_acc_history, f)
        with open(os.path.join(save_dir, 'train_loss_history.pkl'), 'wb') as f:
            pickle.dump(train_loss_history, f)
        print('YADA')

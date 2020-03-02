#### TODO: Currently this fails probably since the available data for the narendra-li was computed using no
# TODO: normalization yet so the model cannot be loaded anymore. But I need to re-compute it anyways..

# import generic libraries
import pandas as pd
import os
import torch
import matplotlib.pyplot as plt

import numpy as np
# import user-written files
import data.loader as loader
import utils.dataevaluater as de
from utils.kalman_filter import run_kalman_filter
from utils.utils import compute_normalizer
# import options files
import options.model_options as model_params
import options.dataset_options as dynsys_params
import options.train_options as train_params
from models.model_state import ModelState
from data.toy_lgssm import run_toy_lgssm_sim

import scipy.io
import matplotlib.style

# set (high level) options dictionary
options = {
    'dataset': 'narendra_li',
    'model': 'STORN',
    'do_train': False,
    'do_test': True,  # ALWAYS
    'logdir': 'ndata',
    'normalize': True,
    'seed': 1234,
    'optim': 'Adam',
    'showfig': True,
    'savefig': False,
}

# get saving path
path_general = os.getcwd() + '/log/{}/{}/run200223/{}/'.format(options['logdir'],
                                                               options['dataset'],
                                                               options['model'], )

# %%
if __name__ == "__main__":
    print('Run file: final_toy_lgssm.py')

    # get correct computing device
    if torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')
    # device = torch.device('cpu')
    print('Device: {}'.format(device))

    # get the options
    options['dataset_options'] = dynsys_params.get_dataset_options(options['dataset'])
    options['model_options'] = model_params.get_model_options(options['model'], options['dataset'],
                                                              options['dataset_options'])
    options['train_options'] = train_params.get_train_options(options['dataset'])
    options['test_options'] = train_params.get_test_options()

    # optimal model parameters
    h_opt = 60  # 60
    z_opt = 20  # 5
    n_opt = 1
    options['model_options'].h_dim = h_opt
    options['model_options'].z_dim = z_opt
    options['model_options'].n_layers = n_opt

    path = path_general + 'data/'
    k_max_chosen = 50000
    file_name_general = 'narendra_li_kmaxtrain_{}'.format(k_max_chosen)

    # select parameters for toy lgssm
    kwargs = {"k_max_train": 50000,
              "k_max_val": 5000,
              "k_max_test": 5000}

    # Specifying datasets
    loaders = loader.load_dataset(dataset=options["dataset"],
                                  dataset_options=options["dataset_options"],
                                  train_batch_size=options["train_options"].batch_size,
                                  test_batch_size=options["test_options"].batch_size,
                                  **kwargs)

    if options['do_test']:
        # %% test the model

        # ##### Loading the model -> This needs to be changed to run for GPU as well!!
        # switch to cpu computations for testing
        options['device'] = 'cpu'

        # Compute normalizers
        if options["normalize"]:
            normalizer_input, normalizer_output = compute_normalizer(loaders['test'])
        else:
            normalizer_input = normalizer_output = None
        # Define model
        modelstate = ModelState(seed=options["seed"],
                                nu=loaders["train"].nu, ny=loaders["train"].ny,
                                model=options["model"],
                                options=options,
                                normalizer_input=normalizer_input,
                                normalizer_output=normalizer_output)
        modelstate.model.to(options['device'])

        # load model
        path = path_general + 'model/'
        file_name = file_name_general + '_bestModel.ckpt'
        modelstate.load_model(path, file_name)
        modelstate.model.to(options['device'])

        # sample from the model
        for i, (u_test, y_test) in enumerate(loaders['test']):
            # getting output distribution parameter only implemented for selected models
            u_test = u_test.to(options['device'])
            y_sample, y_sample_mu, y_sample_sigma = modelstate.model.generate(u_test)

            # convert to numpy for evaluation
            # samples data
            y_sample_mu = y_sample_mu.detach().numpy()
            y_sample_sigma = y_sample_sigma.detach().numpy()
            # test data
            y_test = y_test.detach().numpy()
            y_sample = y_sample.detach().numpy()

        # original test set is unnoisy -> get noisy test set
        yshape = y_test.shape
        y_test_noisy = y_test + np.sqrt(1) * np.random.randn(yshape[0], yshape[1], yshape[2])

        # %% plot time evaluation with uncertainty

        # plot resulting prediction
        data_y_true = [y_test, np.sqrt(1) * np.ones_like(y_test)]
        data_y_sample = [y_sample_mu, y_sample_sigma]

        plt.figure(figsize=(6, 5))
        length = y_test.shape[-1]
        x = np.linspace(0, length - 1, length)
        # ####### plot true output with uncertainty
        mean = y_test.squeeze()
        std = np.sqrt(1) * np.ones_like(mean)
        # plot mean
        plt.plot(mean, label='{}'.format('Test Data, $\mu\pm3\sigma$'))
        # plot 3std around
        plt.fill_between(x, mean, mean + 3 * std, alpha=0.3, facecolor='b')
        plt.fill_between(x, mean, mean - 3 * std, alpha=0.3, facecolor='b')

        # ####### plot samples output with uncertainty
        mean = y_sample_mu.squeeze()
        std = y_sample_sigma.squeeze()
        # plot mean
        plt.plot(mean, label='STORN, $\mu\pm3\sigma$')  # , color='r')
        # plot 3std around
        plt.fill_between(x, mean, mean + 3 * std, alpha=0.3, facecolor='r')
        plt.fill_between(x, mean, mean - 3 * std, alpha=0.3, facecolor='r')

        # #### plot settings
        plt.title('Output of Toy LGSSM')
        plt.ylabel('$y(k)$')
        plt.xlabel('time steps $k$')
        plt.legend()
        plt.xlim([300, 450])
        plt.ylim([-9, 9])

        # storage path
        file_name = '4_lgssm_results_STORN'
        path = path_general + 'timeEval/'
        if options['savefig']:
            # save figure
            # check if path exists and create otherwise
            if not os.path.exists(path):
                os.makedirs(path)
            plt.savefig(path + file_name + '.pdf', format='pdf')
        # plot model
        if options['showfig']:
            plt.show()

        # %% plot errors

        plt.figure(figsize=(6, 5))
        # plot error of PEM
        plt.plot(y_id.squeeze() - y_test.squeeze(), color='k')
        # plot error of STORN
        plt.plot(y_sample_mu.squeeze() - y_test.squeeze(), color='r')

        # editiing
        plt.title('Error to test data')
        plt.ylabel('$y(k)$')
        plt.xlabel('time steps $k$')
        plt.legend()
        plt.xlim([300, 450])

        plt.show()

        # %% test parameter

        print('Performance parameter of NN model:')
        # compute marginal likelihood (same as for predictive distribution loss in training)
        logLikelihood = de.compute_marginalLikelihood(y_test_noisy, y_sample_mu, y_sample_sigma, doprint=True)

        # compute VAF
        vaf = de.compute_vaf(y_test_noisy, y_sample_mu, doprint=True)

        # compute RMSE
        rmse = de.compute_rmse(y_test_noisy, y_sample_mu, doprint=True)

        print('\nPerformance parameter of PEM:')
        # compute VAF
        vaf_id = de.compute_vaf(y_test_noisy, np.expand_dims(y_id, 0), doprint=True)
        # compute RMSE
        rmse_id = de.compute_rmse(y_test_noisy, np.expand_dims(y_id, 0), doprint=True)

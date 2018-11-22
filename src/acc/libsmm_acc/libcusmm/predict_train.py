#!/usr/bin/env python
# -*- coding: utf-8 -*-
####################################################################################################
# Copyright (C) by the DBCSR developers group - All rights reserved                                #
# This file is part of the DBCSR library.                                                          #
#                                                                                                  #
# For information on the license, see the LICENSE file.                                            #
# For further information please visit https://dbcsr.cp2k.org                                      #
# SPDX-License-Identifier: GPL-2.0+                                                                #
####################################################################################################


import os
import sys
import pickle
import datetime
import json
import random
import numpy as np
import pandas as pd
from optparse import OptionParser
from predict_helpers import *
from kernels.cusmm_dnt_helper import to_tuple, to_string


# ===============================================================================
# Selected features and optimized hyperparameters
pre_selected_features = {
    'tiny': [  # 2018-11-26--12-21
        'm',
        'n',
        'k',
        'threads_per_blk',
        'minblocks',
        'mxnxk',
        'size_a',
        'size_b',
        'size_c',
        'grouping',
        'nblks',
        'nthreads',
        'ru_tinysmallmed_unroll_factor_a',
        'ru_tinysmallmed_unroll_factor_a_total',
        'ru_tinysmallmed_unroll_factor_b',
        'ru_tinysmallmed_unroll_factor_b_total',
        'ru_tinysmallmed_unroll_factor_c_total',
        'ru_tiny_max_parallel_work',
        'ru_tiny_smem_per_block',
        'ru_tiny_nsm',
        'Koth_tiny_Nmem'
    ],
    'small': [  # 2018-10-16--15-26
        'grouping',
        'k',
        'm',
        'minblocks',
        'threads_per_blk',
        'nthreads',
        'Gflops',
        'ru_tinysmallmed_unroll_factor_b',
        'ru_smallmedlarge_cmax',
        'ru_smallmedlarge_T',
        'ru_smallmedlarge_min_threads',
        'ru_smallmed_buf_size',
        'Koth_small_Nmem_shared',
    ],
    'medium': [  # From: 2018-11-22--01-38
        'threads_per_blk',
        'mxnxk',
        'size_a',
        'grouping',
        'ru_tinysmallmed_unroll_factor_b',
        'ru_tinysmallmed_unroll_factor_c_total',
        'ru_smallmed_unroll_factor_c',
        'ru_smallmed_loop_matmul',
        'ru_smallmed_max_parallel_work',
        'ru_smallmed_regs_per_thread',
        'ru_smallmedlarge_T',
        'Koth_med_Nmem'

    ],
    'largeDB1': [  # 2018-10-15--02-47
        'size_b',
        'minblocks',
        'tile_n',
        'ru_large_Pc',
        'size_c',
        'size_a',
        'Koth_large_Nmem_glob',
        'nblocks_per_sm_lim_blks_warps',
        'ru_smallmedlarge_cmax',
        'tile_m',
        'm',
        'sm_desired',
        'ru_large_Pa',
        'ru_large_loop_matmul',
        'ru_smallmedlarge_rmax',
        'w',
        'ru_large_unroll_factor_b',
        'threads_per_blk',
        'ru_large_unroll_factor_a',
        'ru_large_Pb',
        'k',
        'Gflops'
    ],
    'largeDB2': [  # 2018-10-15--07-43
        'size_a',
        'size_b',
        'tile_m',
        'sm_desired',
        'ru_smallmedlarge_rmax',
        'ru_large_loop_matmul',
        'm',
        'Koth_large_Nmem_glob',
        'ru_large_unroll_factor_b',
        'tile_n',
        'w',
        'ru_large_Pc',
        'k',
        'ru_smallmedlarge_cmax',
        'ru_large_Pa',
        'ru_large_unroll_factor_a',
        'size_c',
        'threads_per_blk',
    ]
}

optimized_hyperparameters = {  # chosen by common sense, then trial and error
    'tiny': {
        'max_depth': 16,
        'min_samples_leaf': 2,
        'min_samples_split': 15,
        'n_features_to_drop': 2
    },
    'small': {
        'max_depth': 16,
        'min_samples_leaf': 2,
        'min_samples_split': 15,
        'n_features_to_drop': 5
    },
    'medium': {
        'max_depth': 18,
        'min_samples_leaf': 2,
        'min_samples_split': 13,
        'n_features_to_drop': 12
    },
    'largeDB1': {
        'max_depth': 18,
        'min_samples_leaf': 13,
        'min_samples_split': 5,
        'n_features_to_drop': 12
    },
    'largeDB2': {
        'max_depth': 18,
        'min_samples_leaf': 5,
        'min_samples_split': 5,
        'n_features_to_drop': 12
    }
}


# ===============================================================================
# Printing and dumping helpers
def get_log_folder(algo, prefitted_model_folder):
    """Create a unique log folder for this run in which logs, plots etc. will be stored """
    if len(prefitted_model_folder) == 0:

        # Create a new folder for this model
        file_signature = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M")
        folder = os.path.join("model_selection", os.path.join(algo, file_signature))
        log_file = os.path.join(folder, "log.txt")
        if not os.path.exists(folder):
            os.makedirs(folder)

    else:

        # If loading a pre-fitted model, use this pre-fitted model's folder as a log folder, but create a new log file
        folder = prefitted_model_folder
        log_file_signature = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M")
        log_file = os.path.join(folder, "log_" + log_file_signature + ".txt")

    # Log folder and file
    log = ''
    log += print_and_log('\nLogging to:')
    log += print_and_log('\t' + folder)
    log += print_and_log('\t' + log_file)

    return folder, log_file, log


def dump_or_load_options(pgm_options, folder, log):

    options_file_name = os.path.join(folder, 'options.json')

    if len(pgm_options.prefitted_model) == 0:
        # if we're training a model, dump options to folder so they can be reloaded in another run
        print('Dump options to', options_file_name)
        with open(options_file_name, 'w') as f:
            json.dump(pgm_options.__dict__, f)

    else:
        # if we're using a pre-fitted model, load options from that model
        print('Read options from', options_file_name)
        with open(options_file_name, 'r') as f:
            options_dict = json.load(f)

        # overwrite the options that characterize this program run
        characteristic_options = ["in_folder", "algo", "perf_type", "tune", "model", "splits", "ntrees",
                                  "njobs", "nrows"]
        for opt in characteristic_options:
            pgm_options.__dict__[opt] = options_dict[opt]

    # Log options
    log += print_and_log('Predict-train running with options:')
    for opt, opt_val in pgm_options.__dict__.items():
        log += print_and_log('{:<15}: {}'.format(opt, opt_val))

    return pgm_options, log


def print_and_log(msg):
    if not isinstance(msg, str):
        msg = str(msg)
    log = '\n' + msg
    print(msg)
    return log


# ===============================================================================
# Custom loss functions and scorers
def perf_loss(y_true, y_pred, top_k, X_mnk, scaled=True):
    """
    Compute the relative performance losses per mnk if one were to measure the top-k best predicted sets of parameters
    and pick the best out of this top-k

    :param y_true: ground truth performances (performance scaled between 0 and 1)
    :param y_pred: estimated performances (performance scaled between 0 and 1)
    :param top_k: number of top performances to measure
    :param X_mnk: corresponding mnks
    :return: perf_losses: array of relative performance losses (in %), one array element per mnk
    """
    assert len(y_true.index) == y_pred.flatten().size
    assert len(y_true.index) == len(X_mnk.index)

    perf_losses = list()
    mnks = np.unique(X_mnk['mnk'].values)
    for mnk in mnks:

        # Get performances per mnk
        idx_mnk = np.where(X_mnk == mnk)[0].tolist()
        assert (len(idx_mnk) > 0), "idx_mnk is empty"
        y_true_mnk = y_true.iloc[idx_mnk]
        y_pred_mnk = y_pred[idx_mnk]

        # Get top-k best predicted performances
        if top_k != 1:
            top_k_idx = np.argpartition(-y_pred_mnk, top_k)[:top_k]
        else:
            top_k_idx = np.argmax(y_pred_mnk)
        y_correspmax = y_true_mnk.iloc[top_k_idx]

        # Chosen max perf. among predicted max performances
        maxperf_chosen = np.amax(y_correspmax)

        # True Max. performances
        if not scaled:
            maxperf = float(y_true_mnk.max(axis=0))
            assert maxperf >= 0, "Found non-positive value for maxperf: " + str(maxperf)
            perf_loss = (maxperf - maxperf_chosen) / maxperf
        else:
            perf_loss = 1.0 - maxperf_chosen

        # Relative performance loss incurred by using model-predicted parameters instead of autotuned ones [%]
        perf_losses.append(100 * perf_loss)

    return perf_losses


def worse_rel_perf_loss_of_k(y_true, y_pred, top_k, X_mnk, scaled=True):
    y = np.array(perf_loss(y_true, y_pred, top_k, X_mnk, scaled))
    return float(y.max(axis=0))


def mean_rel_perf_loss_of_k(y_true, y_pred, top_k, X_mnk, scaled=True):
    y = np.array(perf_loss(y_true, y_pred, top_k, X_mnk, scaled))
    return float(y.mean(axis=0))


def worse_case_scorer(estimator, X, y, top_k):
    """
    :param estimator: the model that should be evaluated
    :param X: validation data
    :param y: ground truth target for X
    :return: score: a floating point number that quantifies the estimator prediction quality on X, with reference to y
    """
    mnk = pd.DataFrame()
    mnk['mnk'] = X['mnk'].copy()
    y_pred = estimator.predict(X.drop(['mnk'], axis=1))
    score = worse_rel_perf_loss_of_k(y, y_pred, top_k, mnk)
    return -score  # by scikit-learn convention, higher numbers are better, so the value should be negated


def worse_case_scorer_top1(estimator, X, y):
    return worse_case_scorer(estimator, X, y, 1)


def mean_scorer(estimator, X, y, top_k):
    """
    :param estimator: the model that should be evaluated
    :param X: validation data
    :param y: ground truth target for X
    :return: score: a floating point number that quantifies the estimator prediction quality on X, with reference to y
    """
    mnk = pd.DataFrame()
    mnk['mnk'] = X['mnk'].copy()
    y_pred = estimator.predict(X.drop(['mnk'], axis=1))
    score = mean_rel_perf_loss_of_k(y, y_pred, top_k, mnk)
    return -score  # by scikit-learn convention, higher numbers are better, so the value should be negated


def mean_scorer_top1(estimator, X, y):
    return mean_scorer(estimator, X, y, 1)


# ===============================================================================
# Read and prepare data
def get_reference_performances(in_folder, algo, perf_type):
    import json
    maxperf_file = os.path.join(in_folder, 'max_performances.json')
    with open(maxperf_file) as f:
        max_performances = json.load(f)

    maxperf_file = os.path.join(in_folder, 'max_performances_by_algo.json')
    with open(maxperf_file) as f:
        max_performances_algo = json.load(f)[algo]

    max_performances_ref = None
    if perf_type == 'perf_scaled':
        max_performances_ref = max_performances
    elif perf_type == 'perf_scaled_by_algo':
        max_performances_ref = max_performances_algo

    baseline_file = os.path.join(in_folder, 'baseline_performances_by_algo.json')
    with open(baseline_file) as f:
        baseline_performances_algo = json.load(f)[algo]

    return max_performances, max_performances_algo, max_performances_ref, baseline_performances_algo


def read_data(algo, read_from, nrows, perf_type, plot_all, folder, log):

    # ===============================================================================
    # Read data from CSV
    raw_data_file = os.path.join(read_from, 'raw_training_data_' + algo + '.csv')
    log += print_and_log('\nRead raw data from ' + raw_data_file)
    raw_data = pd.read_csv(raw_data_file, index_col=0, nrows=nrows)
    log += print_and_log('raw data    : {:>8,} x {:>8,} ({:>2.3} MB)'
                         .format(raw_data.shape[0], raw_data.shape[1], sys.getsizeof(raw_data)/10**6))

    derived_data_file = os.path.join(read_from, 'training_data_' + algo + '.csv')
    log += print_and_log('\nRead training data from ' + derived_data_file)
    derived_data = pd.read_csv(derived_data_file, index_col=0, nrows=nrows)
    log += print_and_log('derived data    : {:>8,} x {:>8,} ({:>2.3} MB)'
                         .format(derived_data.shape[0], derived_data.shape[1], sys.getsizeof(derived_data)/10**6))

    # ===============================================================================
    # Get 'X'
    to_drop = list()
    if algo in ['tiny', 'small', 'medium']:
        to_drop = ['w', 'v']
        if algo in ['tiny']:
            to_drop += ['tile_m', 'tile_n']
    X = pd.concat([raw_data.drop(to_drop + ['perf (Gflop/s)'], axis=1),
                   derived_data.drop(['perf_squared', 'perf_scaled', 'perf_scaled_by_algo'], axis=1)], axis=1)

    log += print_and_log('X    : {:>8,} x {:>8,} ({:>2.2} MB)'.format(X.shape[0], X.shape[1], sys.getsizeof(X)/10**6))
    n_features = len(list(X.columns))
    predictor_names = X.columns.values
    log += print_and_log('\nPredictor variables: (' + str(n_features) + ')')
    for i, p in enumerate(predictor_names):
        log += print_and_log("\t{:2}) {}".format(i+1, p))

    # ===============================================================================
    # Get 'Y'
    log += print_and_log('\nExtract Y: ' + perf_type)
    Y = pd.DataFrame()
    if perf_type == 'perf':
        Y[perf_type] = raw_data[perf_type + ' (Gflop/s)']
    else:
        Y[perf_type] = derived_data[perf_type]
    Y.dropna(axis=0, inplace=True)
    log += print_and_log('Y    : {:>8,} ({:>2.2} MB)'.format(Y.size, sys.getsizeof(Y)/10**6))
    # ===============================================================================
    # Get 'X_mnk'
    log += print_and_log('\nWrite X_mnk: ' + perf_type)
    X_mnk = pd.DataFrame()
    X_mnk['mnk'] = X['m'].astype(str) + 'x' + X['n'].astype(str) + 'x' + X['k'].astype(str)
    log += print_and_log('X_mnk : {:>8,} ({:>2.2} MB)'.format(X_mnk.size, sys.getsizeof(X_mnk)/10**6))

    if plot_all:
        plot_training_data(Y, X_mnk, algo, folder)

    return X, X_mnk, Y, log


# ===============================================================================
# Predictive modelling
def get_DecisionTree_model(algo, n_features):
    from itertools import chain

    # Fixed parameters
    model_name = "Decision_Tree"
    splitting_criterion = "mse"
    splitter = "best"
    max_features = None
    max_leaf_nodes = None

    # Hyper-parameters to optimize
    if algo == 'medium':
        max_depth = [10, 13, 16, 18, 21, 24]
        min_samples_split = [2, 8, 12, 18]
        min_samples_leaf = [2, 8, 12, 18]
    else:
        if algo == 'tiny':
            step = 3
            max_depth = chain(range(4, int(np.ceil(0.75*n_features)), step),
                              range(int(np.ceil(0.75*n_features)), int(np.ceil(n_features)), step))
            min_samples_split = range(2, 21, step)
            min_samples_leaf = range(2, 21, step)
        else:
            max_depth = chain(range(4, 13, 2), range(15, 19, 3))
            min_samples_split = [2, 5, 13, 18]
            min_samples_leaf = [2, 5, 13, 18]
    param_grid = {
        model_name + '__estimator__' + 'max_depth': list(max_depth),
        model_name + '__estimator__' + 'min_samples_split': list(min_samples_split),
        model_name + '__estimator__' + 'min_samples_leaf': list(min_samples_leaf)
    }

    # Tree model
    from sklearn.tree import DecisionTreeRegressor
    model = DecisionTreeRegressor(
        criterion=splitting_criterion,
        splitter=splitter,
        min_samples_split=optimized_hyperparameters[algo]["min_samples_split"],
        min_samples_leaf=optimized_hyperparameters[algo]["min_samples_leaf"],
        max_depth=optimized_hyperparameters[algo]["max_depth"],
        max_features=max_features,
        max_leaf_nodes=max_leaf_nodes
    )

    from eli5.sklearn import PermutationImportance
    model_perm = PermutationImportance(model, cv=None)

    return model_perm, model_name, param_grid


def get_RandomForest_model(algo, njobs, ntrees):
    from itertools import chain
    from sklearn.ensemble import RandomForestRegressor

    # Fixed parameters
    model_name = "Random_Forest"
    bootstrap = True
    splitting_criterion = "mse"
    max_features = 'sqrt'

    # Parameters to optimize
    step_big = 50
    step_small = 5
    n_estimators = chain(range(1, 10, step_small), range(50, 200, step_big))
    param_grid = {model_name + '__' + 'n_estimators': list(n_estimators)}

    # Random Forest model
    model = RandomForestRegressor(
        criterion=splitting_criterion,
        n_estimators=ntrees,
        min_samples_split=optimized_hyperparameters[algo]["min_samples_split"],
        min_samples_leaf=optimized_hyperparameters[algo]["min_samples_leaf"],
        max_depth=optimized_hyperparameters[algo]["max_depth"],
        bootstrap=bootstrap,
        max_features=max_features,
        n_jobs=njobs
    )

    return model, model_name, param_grid


def get_train_test_partition(to_partition, test, train=None):
    """
    Perform train/test partition
    :param to_partition: sequence of objects to partition
    :param test: ndarray, test-indices
    :param train (optional): ndarray
    :return:
    """
    if train is None:  # Retrieve training indices
        all_indices = set(range(len(to_partition[0].index)))
        train = list(all_indices - set(test))

    partitioned = list()
    for df in to_partition:
        df_train = df.iloc[train, :]          # train: use for hyper-parameter optimization (via CV) and training
        partitioned.append(df_train)
        df_test = df.iloc[test, :]            # test : use for evaluation of 'selected/final' model
        partitioned.append(df_test)

    return partitioned


def train_model(X, X_mnk, Y, options, folder, log):

    # ===============================================================================
    # Get options
    algo = options.algo
    model_to_train = options.model
    splits = options.splits
    njobs = options.njobs
    tune = options.tune
    plot_all = options.plot_all
    ntrees = options.ntrees
    results_file = os.path.join(folder, "feature_tree.p")

    # ===============================================================================
    # Testing splitter (train/test-split)
    from sklearn.model_selection import GroupShuffleSplit
    cv = GroupShuffleSplit(n_splits=2, test_size=0.2)
    train_test_splits = cv.split(X, Y, groups=X_mnk['mnk'])
    train, test = next(train_test_splits)
    X_train, X_test,\
    Y_train, Y_test,\
    X_mnk_train, X_mnk_test = get_train_test_partition([X, Y, X_mnk], test, train)
    plot_train_test_partition(test, train, X_mnk, folder)
    log += print_and_log("\nComplete train/test split, total size=" + str(X.shape) +
                         ", test size=" + str(X_test.shape) + ", train_size=" + str(X_train.shape))
    del X, X_mnk, Y  # free memory

    # ===============================================================================
    # Cross-validation splitter (train/validation-split)
    n_splits = splits
    test_size = 0.3
    cv = GroupShuffleSplit(n_splits=n_splits, test_size=test_size)
    predictor_names = X_train.columns.values
    n_predictors = len(predictor_names)

    # ===============================================================================
    # Predictive model
    if model_to_train == "DT":
        model, model_name, param_grid = get_DecisionTree_model(algo, len(X_train.columns.values))
    elif model_to_train == "RF":
        model, model_name, param_grid = get_RandomForest_model(algo, njobs, ntrees)
    else:
        assert False, "Cannot recognize model: " + model_to_train + ". Options: DT, RF"
    log += print_and_log("\nStart tune/train for model " + model_name + " with parameters:")
    log += print_and_log(model)

    from sklearn.feature_selection import SelectFromModel
    feature_importance_threshold = -np.inf
    max_features = n_predictors - optimized_hyperparameters[algo]['n_features_to_drop']
    split_indices = cv.split(X_train.values, Y_train.values, groups=X_mnk_train.values)
    model.cv = split_indices
    model.fit(X_train.values, Y_train.values)
    model_fs = SelectFromModel(model, threshold=feature_importance_threshold, max_features=max_features, prefit=True)
    print(model_fs)

    if tune:  # Perform feature selection and hyperparameter optimization

        log += print_and_log('----------------------------------------------------------------------------')
        log += print_and_log("\nBuild Pipeline")

        # ===============================================================================
        # Feature selection
        log += print_and_log("Selecting optimal features among:\n" + str(predictor_names) + '\n')

        feature_selection_name = 'select_features'

        from sklearn.pipeline import Pipeline
        pipe = Pipeline(steps=[
            (feature_selection_name, model_fs),
            (model_name, model)
        ])

        # ===============================================================================
        # Hyperparameter optimization (Grid search)
        log += print_and_log('Parameter grid:')
        for par_name, par_value in param_grid.items():
            log += print_and_log('{}: {}'.format(par_name, par_value))

        from sklearn.model_selection import GridSearchCV
        if algo in ['tiny', 'largeDB1', 'largeDB2']:
            verbosity_level = 2
        else:
            verbosity_level = 2
        gs = GridSearchCV(
            estimator=pipe,
            param_grid=param_grid,
            cv=cv,
            scoring=mean_scorer_top1,
            pre_dispatch=8,
            n_jobs=njobs,
            verbose=verbosity_level,
            return_train_score=False
        )

        # ===============================================================================
        # Fit and get best feature selection and model
        log += print_and_log('\n----------------------------------------------------------------------------')
        log += print_and_log('Start fit')
        X_train["mnk"] = X_mnk_train['mnk']  # add to X-DataFrame (needed for scoring function)
        gs.fit(X_train, Y_train, X_mnk_train['mnk'], ignore_in_fit=["mnk"])
        best_pipe = gs.best_estimator_.get_params()
        best_feature_selection = best_pipe[feature_selection_name]
        best_model = best_pipe[model_name]

        # ===============================================================================
        # Info on feature selection
        all_feature_names = X_train.columns.values.tolist()
        all_feature_names.remove('mnk')
        feature_support = best_feature_selection.get_support()
        features_importances = best_feature_selection.estimator_.feature_importances_
        feature_name_importance = zip(all_feature_names, features_importances, feature_support)
        feature_name_importance = sorted(feature_name_importance, key=lambda x: x[1], reverse=True)

        log += print_and_log('\n----------------------------------------------------------------------------')
        n_selected_features = np.sum(feature_support)
        log += print_and_log("Optimal number of features : {}".format(n_selected_features))

        # Selected features
        log += print_and_log("\nFeatures:")
        selected_features = list()
        selected_feature_importances = list()
        for i, (feat_name, feat_imp, feat_in) in enumerate(feature_name_importance):
            in_or_out = 'accepted' if feat_in else ' x rejected'
            log += print_and_log("{:>2}) {:<28}, imp: {:>1.3f} {}".format(i+1, feat_name, feat_imp, in_or_out))
            if feat_in:
                selected_features.append(feat_name)
                selected_feature_importances.append(feat_imp)

        # Drop non-selected features
        features_to_drop = [f for f in predictor_names if f not in selected_features]
        X_train = X_train.drop(features_to_drop, axis=1)
        X_train = X_train.drop(['mnk'], axis=1)
        X_test = X_test.drop(features_to_drop, axis=1)

        print('Refiting underlying model...')
        best_model = best_model.wrapped_estimator_
        best_model.fit(X_train, Y_train)

        log += print_and_log("\nPlot feature importance:")
        plot_feature_importance(selected_feature_importances, selected_features, folder)

        # ===============================================================================
        # Info on GridSearch
        describe_hpo(gs, X_test, Y_test, '', plot_all)

        safe_pickle([gs.param_grid, gs.cv_results_, gs.best_params_], os.path.join(folder, "cv_results.p"))
        safe_pickle([selected_features, best_model, test], results_file)

        plot_cv_scores(gs.param_grid, gs.cv_results_, gs.best_params_, folder, algo, splits)

        log += print_and_log("\nCompleted hyperparameter optimization, wrote results to " + results_file)
        log += print_and_log('----------------------------------------------------------------------------')
        return_model = best_model

    else:

        featsel = True
        if featsel:

            # ===============================================================================
            # Info on feature selection
            all_feature_names = X_train.columns.values.tolist()
            feature_support = model_fs.get_support()
            features_importances = model.feature_importances_
            feature_name_importance = zip(all_feature_names, features_importances, feature_support)
            feature_name_importance = sorted(feature_name_importance, key=lambda x: x[1], reverse=True)

            log += print_and_log('\n----------------------------------------------------------------------------')
            n_selected_features = np.sum(feature_support)
            log += print_and_log("Optimal number of features : {}".format(n_selected_features))

            # Selected features
            log += print_and_log("\nFeatures:")
            selected_features = list()
            selected_feature_importances = list()
            for i, (feat_name, feat_imp, feat_in) in enumerate(feature_name_importance):
                in_or_out = 'accepted' if feat_in else ' x rejected'
                log += print_and_log("{:>2}) {:<40}, imp: {:>1.3f} {}".format(i + 1, feat_name, feat_imp, in_or_out))
                if feat_in:
                    selected_features.append(feat_name)
                    selected_feature_importances.append(feat_imp)

            # Drop non-selected features
            features_to_drop = [f for f in predictor_names if f not in selected_features]
            X_train = X_train.drop(features_to_drop, axis=1)
            X_test = X_test.drop(features_to_drop, axis=1)
            model.cv = None

        else:
            # ===============================================================================
            # Load selected features and hyperparameters
            selected_features = pre_selected_features[algo]
            features_to_drop = [f for f in predictor_names if f not in selected_features]
            X_train = X_train.drop(features_to_drop, axis=1)
            X_test = X_test.drop(features_to_drop, axis=1)

        # ===============================================================================
        # Fit
        log += print_and_log('----------------------------------------------------------------------------')
        log += print_and_log("\nStart fitting model with predictors:\n")
        for i, p in enumerate(X_train.columns.values):
            log += print_and_log("\t{:>2}) {}".format(i+1, p))

        model.fit(X_train, Y_train)

        safe_pickle([X_train.columns.values, model, test], results_file)
        log += print_and_log("\nCompleted fit, wrote results to " + results_file)
        log += print_and_log('----------------------------------------------------------------------------')
        return_model = model

    # Return
    if 'mnk' in X_train.columns.values:
        X_train.drop('mnk', axis=1, inplace=True)
    if 'mnk' in X_test.columns.values:
        X_train.drop('mnk', axis=1, inplace=True)

    return X_train, Y_train, X_mnk_train, \
           X_test, Y_test, X_mnk_test, \
           return_model, log


def fetch_pre_trained_model(X, X_mnk, Y, model_path, log):

    # Load pre-trained model, selected features and indices of test-set
    features, model, test_indices = safe_pickle_load(os.path.join(model_path, 'feature_tree.p'))
    if 'mnk' in features:
        features.remove('mnk')

    log += print_and_log("\nPerform train/test split")
    X_train, X_test, \
    Y_train, Y_test, \
    X_mnk_train, X_mnk_test = get_train_test_partition([X, Y, X_mnk], test_indices)
    log += print_and_log(
        "\nComplete train/test split, total size=" + str(X.shape) + ", test size=" + str(X_test.shape) +
        ", train_size=" + str(X_train.shape))
    assert X_test.shape[0] < X_train.shape[0]

    log += print_and_log("\nDrop non-selected features")
    predictor_names = X_train.columns.values.tolist()
    features_to_drop = [f for f in predictor_names if f not in features]
    X_train.drop(features_to_drop, axis=1, inplace=True)
    X_test.drop(features_to_drop, axis=1, inplace=True)

    return X_train, Y_train, X_mnk_train, \
           X_test, Y_test, X_mnk_test, \
           model, log


# ===============================================================================
# Describe and evaluate model
def describe_hpo(gs, X, Y, log, plot_all):
    predictor_names = X.columns.values.tolist()
    log += print_and_log('\n----------------------------------------------------------------------------')
    log += print_and_log('Predictor variables:')
    for p in predictor_names:
        log += print_and_log("\t{}".format(p))

    log += print_and_log("\nBest parameters set found on development set:")
    for bestpar_name, bestpar_value in gs.best_params_.items():
        log += print_and_log("\t{}: {}".format(bestpar_name, bestpar_value))

    log += print_and_log("\nBest estimator:")
    best_estimator = gs.best_estimator_._final_estimator
    log += print_and_log(best_estimator)
    log += print_and_log('----------------------------------------------------------------------------')

    # Export tree SVG
    if plot_all:
        from dtreeviz.trees import dtreeviz
        log += print_and_log('\nExport tree to SVG:')
        viz = dtreeviz(best_estimator, X.values, Y.values.ravel(),
                       target_name='perf',
                       feature_names=predictor_names)
        viz.save("trytree.svg")
        viz.view()

    return log


def describe_model(model, X, Y, log, plot_all):
    predictor_names = X.columns.values.tolist()
    log += print_and_log('Model:')
    log += print_and_log(model)

    log += print_and_log('Predictor variables:')
    for p in predictor_names:
        log += print_and_log("\t{}".format(p))

    # Export tree SVG
    if plot_all:
        from dtreeviz.trees import dtreeviz
        log += print_and_log('\nExport tree to SVG:')
        viz = dtreeviz(model, X.values, Y.values.ravel(),
                       target_name='perf',
                       feature_names=predictor_names)
        viz.save("trytree.svg")
        viz.view()

    return log


def print_error(y_true, y_pred, X_mnk, log, scaled=True):
    result_line = "Relative performance loss compared to autotuned max:\n" + \
                  "top-{}: worse: {:>6.3f} [%], mean: {:>6.3f} [%]"
    for top_k in [1]:
        log += print_and_log(result_line.format(top_k,
                                                worse_rel_perf_loss_of_k(y_true, y_pred, top_k, X_mnk, scaled),
                                                mean_rel_perf_loss_of_k(y_true, y_pred, top_k, X_mnk, scaled)))
    return log


def scale_back(y_scaled, x_mnk, max_performances):
    corresponding_maxperf = np.array([max_performances[mnk] for mnk in x_mnk['mnk'].values.tolist()])
    return y_scaled * corresponding_maxperf


def plot_train_test_partition(test_idx, train_idx, X_mnk, folder):

    import matplotlib.pyplot as plt

    mnks_string_train = X_mnk['mnk'].iloc[train_idx].unique()
    mnks_train = to_tuple(*mnks_string_train)
    mnks_string_test = X_mnk['mnk'].iloc[test_idx].unique()
    mnks_test = to_tuple(*mnks_string_test)

    y_train_product = dict()  # keys: m*n*k, values: how many times this mnk-product appears in training-mnks
    for m, n, k in mnks_train:
        mxnxk = m*n*k
        if mxnxk in y_train_product.keys():
            y_train_product[mxnxk] += 1
        else:
            y_train_product[mxnxk] = 1

    train_mnks = list()
    train_counts = list()
    for mnk, count in y_train_product.items():
        for c in range(count):
            train_mnks.append(mnk)
            train_counts.append(c+1)

    y_test_product = dict()
    for m, n, k in mnks_test:
        mxnxk = m*n*k
        if mxnxk in y_test_product.keys():
            y_test_product[mxnxk] += 1
        else:
            y_test_product[mxnxk] = 1

    test_mnks = list()
    test_counts = list()
    for mnk, count in y_test_product.items():
        for c in range(count):
            test_mnks.append(mnk)
            if mnk in y_train_product.keys():
                test_counts.append(y_train_product[mnk] + c+1)
            else:
                test_counts.append(c+1)

    plt.figure(figsize=(30, 5))
    markersize = 12
    plt.plot(train_mnks, train_counts, 'o', markersize=markersize, color='blue', label="training mnks (" + str(len(train_mnks)) + ")")
    plt.plot(test_mnks, test_counts, 'o', markersize=markersize, color='red', label="testing mnks (" + str(len(test_mnks)) + ")")
    plot_file_path = os.path.join(folder, "train-test_split.svg")
    plt.xlabel('m * n * k triplets')
    plt.ylabel('number of occurences in data set')
    plt.title('Train/test split')
    maxcount = max(max(test_counts), max(train_counts)) + 1
    plt.ylim([0, maxcount])
    plt.legend()
    plt.savefig(plot_file_path)


def plot_rfecv(rfecv, folder):
    # Plot number of features VS. cross-validation scores
    plt.figure()
    plt.xlabel("Number of features selected")
    plt.ylabel("Cross validation score (nb of correct classifications)")
    plt.plot(range(1, len(rfecv.grid_scores_) + 1), rfecv.grid_scores_)
    plot_file_path = os.path.join(folder, "rfecv_scores.svg")
    plt.savefig(plot_file_path)
    print(plot_file_path)


def plot_feature_importance(importances, names, folder):

    plt.rcdefaults()
    fig, ax = plt.subplots()

    ax.set_title("Feature importances")
    ax.barh(range(len(names)), importances, color="g", align="center")
    ax.set_yticks(np.arange(len(importances)))
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    plot_file_path = os.path.join(folder, "feature_importance.svg")
    plt.savefig(plot_file_path)
    print(plot_file_path)


def plot_loss_histogram(y_true, y_pred, X_mnk, folder):
    import matplotlib.pyplot as plt

    # Get losses
    top_k = 1
    y = np.array(perf_loss(y_true, y_pred, top_k, X_mnk, False))

    # Losses-histogram
    num_bins = 100
    plt.figure()
    plt.hist(y, num_bins, facecolor='green', alpha=0.75)
    plt.xlabel("relative performance loss [%]")
    plt.ylabel("# occurrences")
    plt.title("Performance losses for top-k=" + str(top_k) + " (" + str(len(y)) + " test mnks)")
    plot_file_path = os.path.join(folder, "result_losses.svg")
    plt.savefig(plot_file_path)
    print(plot_file_path)


def plot_prediction_accuracy(m, n, k, y_true, y_pred, train, pp):
    import matplotlib.pyplot as plt

    plt.figure()
    if train:
        plt.plot(100 * y_true, 100 * y_pred, 'b.', label='truth')
    else:
        plt.plot(100 * y_true, 100 * y_pred, 'r.', label='truth')
    plt.xlabel("true scaled performance [%]")
    plt.ylabel("predicted scaled performance [%]")
    type = 'train' if train else 'test'
    plt.title("Prediction accuracy for kernel " + str((m, n, k)) + " (" + type + ")")
    pp.savefig()


def plot_cv_scores(param_grid, results, best_pars, folder, algo, splits):
    """Plot cross-validation scores on the hyper parameter grid search. Inspired by
    http://scikit-learn.org/stable/auto_examples/model_selection/plot_multi_metric_evaluation.html"""

    import matplotlib.pyplot as plt
    for p in param_grid.keys():

        plt.figure()
        plt.title("CV scores (" + algo + ")")
        plt.xlabel("parameter: " + p + " (chosen: " + str(best_pars[p]) + ")")
        plt.ylabel("cv-score: relative perf loss [%] (mean over " + str(splits) + " folds)")
        ax = plt.gca()

        # Get the regular numpy array from the dataframe
        results_ = pd.DataFrame(results)
        groups_to_fix = list(best_pars.keys())
        groups_to_fix.remove(p)
        for g in groups_to_fix:
            results_ = results_.groupby('param_' + g).get_group(best_pars[g])
        X_axis = np.array(results_['param_' + p].values, dtype=float)
        X_axis_p = results_['param_' + p]

        sample = 'test'
        style = '-'
        scorer = 'score'
        color = 'b'
        sample_score_mean = results_['mean_%s_%s' % (sample, scorer)]
        sample_score_std = results_['std_%s_%s' % (sample, scorer)]
        ax.fill_between(X_axis, sample_score_mean - sample_score_std,
                        sample_score_mean + sample_score_std,
                        alpha=0.05, color=color)
        ax.plot(X_axis, sample_score_mean, style, color=color,
                alpha=1 if sample == 'test' else 0.7,
                label="%s (%s)" % (scorer, sample))

        best_index = np.argmin(results['rank_test_%s' % scorer])
        best_score = results['mean_test_%s' % scorer][best_index]

        # Annotate the best score for that scorer
        ax.annotate("%0.2f" % best_score,
                    (X_axis_p[best_index], best_score + 0.005))

        plt.legend(loc="best")
        plt.grid(False)

        plot_file_path = os.path.join(folder, "cv_results_" + algo + "_" + p + ".svg")
        plt.savefig(plot_file_path)
        print(plot_file_path)


def get_predive_model_performances(y_true, y_pred, x_mnk, max_performances_ref, max_performances_algo, perf_type):

    mnk_string_pattern = re.compile("(\d+)x(\d+)x(\d+)")
    predictive_model_perf_scaled = dict()
    predictive_model_perf = dict()

    if perf_type in ['perf_scaled', 'perf_scaled_by_algo']:
        for mnk_string in x_mnk['mnk'].unique():

            idx_mnk = np.where(x_mnk == mnk_string)[0].tolist()
            assert (len(idx_mnk) > 0), "idx_mnk is empty"
            m, n, k = mnk_string_pattern.match(mnk_string).groups()

            perf_chosen_idx = np.argmax(y_pred[idx_mnk])
            perf_effective = y_true.iloc[idx_mnk].iloc[perf_chosen_idx].values.item()
            predictive_model_perf_scaled[(int(m), int(n), int(k))] = perf_effective  # 'scaled' according to perf_type
                                                                                     # (i.e. could be by algo or not)

        predictive_model_perf = dict(zip(
            predictive_model_perf_scaled.keys(),
            [perf_scaled * max_performances_ref[to_string(mnk)[0]]
             for mnk, perf_scaled in predictive_model_perf_scaled.items()],
        ))

    else:

        for mnk_string in x_mnk['mnk'].unique():

            idx_mnk = np.where(x_mnk == mnk_string)[0].tolist()
            assert (len(idx_mnk) > 0), "idx_mnk is empty"
            m, n, k = mnk_string_pattern.match(mnk_string).groups()

            perf_chosen_idx = np.argmax(y_pred[idx_mnk])
            perf_effective = y_true.iloc[idx_mnk].iloc[perf_chosen_idx].values.item()
            predictive_model_perf[(int(m), int(n), int(k))] = perf_effective  # 'scaled' according to perf_type
                                                                              # (i.e. could be by algo or not)

    if perf_type in ['perf', 'perf_scaled']:

        # Re-scale performances by algorithm for a fair comparison
        predictive_model_perf_scaled = dict(zip(
            predictive_model_perf.keys(),
            [perf / max_performances_algo[mnk]
             for mnk, perf in predictive_model_perf.items()],
        ))

    return predictive_model_perf, predictive_model_perf_scaled


# ===============================================================================
def evaluate_model(model,
                   X_train, X_mnk_train, Y_train,
                   X_test, X_mnk_test, Y_test,
                   max_performances_ref, max_performances_algo, baseline_performances_algo,
                   options, log, folder):
    """Main evaluation function"""

    scaled_perf = True if options.perf_type in ['perf_scaled', 'perf_scaled_by_algo'] else False

    log += print_and_log('----------------------------------------------------------------------------')
    log += print_and_log('Start model evaluation')
    log = describe_model(model, X_test, Y_test, log, options.plot_all)

    # Training error
    y_train_pred = model.predict(X_train)
    log += print_and_log('\nTraining error: (train&val)')
    log = print_error(Y_train, y_train_pred, X_mnk_train, log, scaled_perf)

    # Test error
    y_test_pred = model.predict(X_test)
    log += print_and_log('\nTesting error:')
    log = print_error(Y_test, y_test_pred, X_mnk_test, log, scaled_perf)

    if options.perf_type in ['perf_scaled', 'perf_scaled_by_algo']:  # TODO: remove 'perf_scaled_by_algo'

        # Really I should do this only for perf_scaled
        # keep it around as a sanity test

        # Training error (scaled-back)
        log += print_and_log('\nTraining error (scaled back): (train&val)')
        y_train_pred_scaled_back = scale_back(y_train_pred, X_mnk_train, max_performances_ref)
        y_train_scaled_back = pd.DataFrame(scale_back(Y_train.values.flatten(), X_mnk_train, max_performances_ref))
        log = print_error(y_train_scaled_back, y_train_pred_scaled_back, X_mnk_train, log, False)

        # Test error (scaled-back)
        log += print_and_log('\nTesting error (scaled back): (test&val)')
        y_test_pred_scaled_back = scale_back(y_test_pred, X_mnk_test, max_performances_ref)
        y_test_scaled_back = pd.DataFrame(scale_back(Y_test.values.flatten(), X_mnk_test, max_performances_ref))
        log = print_error(y_test_scaled_back, y_test_pred_scaled_back, X_mnk_test, log, False)

    # ===============================================================================
    # Print histogram for "best" estimator
    log += print_and_log('\nPlot result histogram:')
    plot_loss_histogram(Y_test, y_test_pred, X_mnk_test, folder)

    # ===============================================================================
    # Plot CV results by evaluation metric
    if options.tune:
        cv_results_file = os.path.join(options.prefitted_model, "cv_results.p")
        if os.path.exists(cv_results_file):
            param_grid, cv_results, best_params = pickle.load(open(cv_results_file, 'rb'))
            log += print_and_log('\nPlot CV scores:')
            plot_cv_scores(param_grid, cv_results, best_params, folder, options.algo, options.splits)
        else:
            print("File", cv_results_file, "does not exist")

    # ===============================================================================
    # Plot prediction accuracy and goodness of choice for a few mnks (training-set)
    n_samples = 10
    mnks_to_plot = random.sample(X_mnk_train['mnk'].values.tolist(), n_samples)
    mnk_string_pattern = re.compile("(\d+)x(\d+)x(\d+)")

    from matplotlib.backends.backend_pdf import PdfPages
    plot_file_path = os.path.join(folder, 'evaluation_by_mnk.pdf')
    pp = PdfPages(plot_file_path)

    for mnk_string in mnks_to_plot:

        # Get performances per mnk
        idx_mnk = np.where(X_mnk_train == mnk_string)[0].tolist()
        assert (len(idx_mnk) > 0), "idx_mnk is empty"
        mnk = mnk_string_pattern.match(mnk_string).groups()
        m_, n_, k_ = mnk

        log += print_and_log('Prediction accuracy plot: ' + str(mnk_string))
        plot_prediction_accuracy(int(m_), int(n_), int(k_), Y_train.iloc[idx_mnk], y_train_pred[idx_mnk], True, pp)

        log += print_and_log('Goodness plot: ' + str(mnk_string))
        plot_choice_goodness(int(m_), int(n_), int(k_), baseline_performances_algo, max_performances_ref,
                             Y_train.iloc[idx_mnk].values, y_train_pred[idx_mnk], True, pp, scaled_perf)

    # ===============================================================================
    # Plot prediction accuracy for a few mnks (testing-set)
    mnks_to_plot = random.sample(X_mnk_test['mnk'].values.tolist(), n_samples)
    for mnk_string in mnks_to_plot:

        # Get performances per mnk
        idx_mnk = np.where(X_mnk_test == mnk_string)[0].tolist()
        assert (len(idx_mnk) > 0), "idx_mnk is empty"
        mnk = mnk_string_pattern.match(mnk_string).groups()
        m_, n_, k_ = mnk

        log += print_and_log('Prediction accuracy plot: ' + str(mnk_string))
        plot_prediction_accuracy(int(m_), int(n_), int(k_), Y_test.iloc[idx_mnk], y_test_pred[idx_mnk], False, pp)

        log += print_and_log('Goodness plot: ' + str(mnk_string))
        plot_choice_goodness(int(m_), int(n_), int(k_), baseline_performances_algo, max_performances_ref,
                             Y_test.iloc[idx_mnk].values, y_test_pred[idx_mnk], False, pp, scaled_perf)

    pp.close()

    # ===============================================================================
    # Scale baseline and max performances
    def to_tuple(mnk_string):
        m, n, k = mnk_string_pattern.match(mnk_string).groups()
        return int(m), int(n), int(k)
    max_performances_algo = dict(zip(
        [to_tuple(mnk_string) for mnk_string in max_performances_algo.keys()],
        max_performances_algo.values()
    ))
    max_performances_algo_scaled = dict(zip(max_performances_algo.keys(), [1.0] * len(max_performances_algo)))
    baseline_performances_algo = dict(zip(
        [to_tuple(mnk_string) for mnk_string in baseline_performances_algo.keys()],
        baseline_performances_algo.values()
    ))
    baseline_performances_algo_scaled = dict(zip(
        [(m, n, k) for m, n, k in baseline_performances_algo.keys()],
        [perf / max_performances_algo[(m, n, k)]
         for (m, n, k), perf in baseline_performances_algo.items()]
    ))

    # ===============================================================================
    # Compare max performances and baseline
    from matplotlib.backends.backend_pdf import PdfPages
    plot_file_path = os.path.join(folder, 'evaluation_overall.pdf')
    pp = PdfPages(plot_file_path)

    plot_performance_gains(max_performances_algo, baseline_performances_algo, 'trained',
                           'max. performance per algorithm', 'baseline per algorithm', pp)
    plot_scaled_performance_gains(max_performances_algo_scaled, baseline_performances_algo_scaled, 'trained',
                                  'max. performance per algorithm', 'baseline per algorithm', pp)

    # ===============================================================================
    # 'Results' = y_true ( y_chosen )
    predictive_model_perf_train, predictive_model_perf_train_scaled = \
        get_predive_model_performances(Y_train, y_train_pred, X_mnk_train,
                                       max_performances_ref, max_performances_algo, options.perf_type)

    predictive_model_perf_test, predictive_model_perf_test_scaled = \
        get_predive_model_performances(Y_test, y_test_pred, X_mnk_test,
                                       max_performances_ref, max_performances_algo, options.perf_type)

    # ===============================================================================
    # Plot results (training set: predictive modelling VS naïve)
    log += print_and_log('\nPredictive model VS baseline: ')

    perf_gain_pred_train_over_baseline = performance_gain(baseline_performances_algo,
                                                          predictive_model_perf_train)
    plot_absolute_performance_gain(perf_gain_pred_train_over_baseline, 'trained',
                                   'baseline per algorithm', 'predictive model', pp)

    scaled_perf_gain_pred_train_over_baseline = performance_gain(baseline_performances_algo_scaled,
                                                                 predictive_model_perf_train_scaled)
    plot_relative_performance_gain(scaled_perf_gain_pred_train_over_baseline, 'trained',
                                   'baseline per algorithm', 'predictive model', pp)

    perf_gain_pred_test_over_baseline = performance_gain(baseline_performances_algo,
                                                         predictive_model_perf_test)
    plot_absolute_performance_gain(perf_gain_pred_test_over_baseline, 'tested',
                                   'baseline per algorithm', 'predictive model', pp)

    scaled_perf_gain_pred_test_over_baseline = performance_gain(baseline_performances_algo_scaled,
                                                                predictive_model_perf_test_scaled)
    plot_relative_performance_gain(scaled_perf_gain_pred_test_over_baseline, 'tested',
                                   'baseline per algorithm', 'predictive model', pp)

    log += print_and_log('\nPredictive model VS autotuned: ')
    perf_gain_pred_train_over_max = performance_gain(max_performances_algo,
                                                     predictive_model_perf_train)
    plot_absolute_performance_gain(perf_gain_pred_train_over_max, 'trained',
                                   'max. performance per algorithm', 'predictive model', pp)
    scaled_perf_gain_pred_train_over_max = performance_gain(max_performances_algo_scaled,
                                                            predictive_model_perf_train_scaled)
    plot_relative_performance_gain(scaled_perf_gain_pred_train_over_max, 'trained',
                                   'max. performance per algorithm', 'predictive model', pp)
    perf_gain_pred_test_over_max = performance_gain(max_performances_algo,
                                                    predictive_model_perf_test)
    plot_absolute_performance_gain(perf_gain_pred_test_over_max, 'tested',
                                   'max. performance per algorithm', 'predictive model', pp)
    scaled_perf_gain_pred_test_over_max = performance_gain(max_performances_algo_scaled,
                                                           predictive_model_perf_test_scaled)
    plot_relative_performance_gain(scaled_perf_gain_pred_test_over_max, 'tested',
                                   'max. performance per algorithm', 'predictive model', pp)

    log += print_and_log('\nCompare performances: ')
    plot_performance_gains(baseline_performances_algo, predictive_model_perf_train, 'trained',
                           'baseline per algorithm', 'predictive model', pp)
    plot_performance_gains(max_performances_algo, predictive_model_perf_train, 'trained',
                           'max. performance per algorithm', 'predictive model', pp)
    plot_performance_gains(baseline_performances_algo, predictive_model_perf_test, 'tested',
                           'baseline per algorithm', 'predictive model', pp)
    plot_performance_gains(max_performances_algo, predictive_model_perf_test, 'tested',
                           'max. performance per algorithm', 'predictive model', pp)

    pp.close()

    return log


# ===============================================================================
# Main
def main():

    parser = OptionParser()
    parser.add_option('-f', '--in_folder', metavar="foldername/",
                      #default='tune_dataset/',
                      #default='tune_sample_25_to_32/',
                      default='tune_sample_4_to_12_logs_and_compileinfo',
                      help='Folder from which to read data')
    parser.add_option('-a', '--algo', metavar="algoname",
                      #default='tiny',
                      #default='small',
                      default='medium',
                      #default='largeDB1',
                      #default='largeDB2',
                      help='Algorithm to train on')
    parser.add_option("-d", "--perf_type", metavar="PERFTYPE",
                      default="perf_scaled",
                      #default="perf_scaled_by_algo",
                      help="Type of performance. " +
                           "Options: perf, perf_squared, perf_scaled, perf_scaled_by_algo. Default: %default")
    parser.add_option('-c', '--plot_all',
                      default=False,
                      help='Plot more stuff' +
                           '(Warning: can be very slow for large trees and create very large files)')
    parser.add_option('-t', '--tune',
                      default=False,
                      help='Rune recursive feature selection and grid search on hyperparameters')
    parser.add_option('-m', '--model',
                      default='DT',
                      help='Model to train. Options: DT (Decision Trees), RF (Random Forests)')
    parser.add_option('-s', '--splits',
                      default=3, metavar="NUMBER", type="int",
                      help='Number of cross-validation splits used in RFECV and GridSearchCV')
    parser.add_option('-e', '--ntrees',
                      default=3, metavar="NUMBER", type="int",
                      help='Number of estimators in RF')
    parser.add_option('-j', '--njobs',
                      default=-1, metavar="NUMBER", type="int",
                      help='Number of cross-validation splits used in RFECV and GridSearchCV')
    parser.add_option('-r', '--nrows',
                      default=None, metavar="NUMBER", type="int",
                      help='Number of rows of data to load. Default: None (load all)')
    parser.add_option('-g', '--prefitted_model',
                      metavar="filename",
                      default='',
                      #default='model_selection/tiny/2018-11-20--10-34_tune_4-12/',
                      #default='model_selection/tiny/2018-11-19--09-50/',
                      #default='model_selection/tiny/2018-11-07--12-01',
                      #default='model_selection/tiny/2018-11-07--16-10',
                      #default='model_selection/tiny/2018-11-21--11-32',
                      help='Path to pickled GridSearchCV object to load instead of recomputing')
    options, args = parser.parse_args(sys.argv)

    # ===============================================================================
    # Create folder to store results of this training and start a log
    folder, log_file, log = get_log_folder(options.algo, options.prefitted_model)

    # ===============================================================================
    # Override algorithm option if working on a pre-fitted model, and log program options
    log += print_and_log('----------------------------------------------------------------------------')
    options, log = dump_or_load_options(options, folder, log)

    # ===============================================================================
    # Get maximum and baseline performances
    max_performances, max_performances_algo, max_performances_ref, baseline_performances_algo = \
        get_reference_performances(options.in_folder, options.algo, options.perf_type)

    # ===============================================================================
    # Read data
    log += print_and_log('----------------------------------------------------------------------------')
    X, X_mnk, Y, log = \
        read_data(options.algo, options.in_folder, options.nrows, options.perf_type, options.plot_all, folder, log)

    # ===============================================================================
    # Get or train model
    log += print_and_log('----------------------------------------------------------------------------')
    if len(options.prefitted_model) == 0:  # train a model

        log += print_and_log("\nPreparing to fit model...")
        X_train, Y_train, X_mnk_train, \
        X_test, Y_test, X_mnk_test, \
        model, log = \
            train_model(X, X_mnk, Y, options, folder, log)

    else:  # load pre-trained model

        log += print_and_log("\nReading pre-fitted model from " + options.prefitted_model)
        X_train, Y_train, X_mnk_train, \
        X_test, Y_test, X_mnk_test, \
        model, log = \
            fetch_pre_trained_model(X, X_mnk, Y, options.prefitted_model, log)

    # ===============================================================================
    # Evaluate model
    log = evaluate_model(model, X_train, X_mnk_train, Y_train, X_test, X_mnk_test, Y_test,
                         max_performances_ref, max_performances_algo, baseline_performances_algo,
                         options, log, folder)

    # ===============================================================================
    # Print log
    log += print_and_log('----------------------------------------------------------------------------')
    with open(log_file, 'w') as f:
        f.write(log)


# ===============================================================================
main()

#EOF

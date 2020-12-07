import sys
import traceback
from collections import namedtuple, OrderedDict

import numpy as np
import pandas as pd

from evalml.exceptions import PipelineScoreError
from evalml.model_family import ModelFamily
from evalml.model_understanding.prediction_explanations._report_creator_factory import (
    _report_creator_factory
)
from evalml.model_understanding.prediction_explanations._user_interface import (
    _make_single_prediction_shap_table
)
from evalml.problem_types import ProblemTypes

# Container for all of the pipeline-related data we need to create reports. Helps standardize APIs of report makers.
_ReportData = namedtuple("ReportData", ["pipeline", "input_features",
                                        "y_true", "y_pred", "y_pred_values", "errors", "index_list", "metric"])


def explain_prediction(pipeline, input_features, top_k=3, training_data=None, include_shap_values=False,
                       output_format="text"):
    """Creates table summarizing the top_k positive and top_k negative contributing features to the prediction of a single datapoint.

    XGBoost models and CatBoost multiclass classifiers are not currently supported.

    Arguments:
        pipeline (PipelineBase): Fitted pipeline whose predictions we want to explain with SHAP.
        input_features (pd.DataFrame): Dataframe of features - needs to correspond to data the pipeline was fit on.
        top_k (int): How many of the highest/lowest features to include in the table.
        training_data (pd.DataFrame): Training data the pipeline was fit on.
            This is required for non-tree estimators because we need a sample of training data for the KernelSHAP algorithm.
        include_shap_values (bool): Whether the SHAP values should be included in an extra column in the output.
            Default is False.
        output_format (str): Either "text" or "dict". Default is "text".

    Returns:
        str or dict - A report explaining the most positive/negative contributing features to the predictions.
    """
    if output_format not in {"text", "dict"}:
        raise ValueError(f"Parameter output_format must be either text or dict. Received {output_format}")
    return _make_single_prediction_shap_table(pipeline, input_features, top_k, training_data, include_shap_values,
                                              output_format=output_format)


def abs_error(y_true, y_pred):
    """Computes the absolute error per data point for regression problems.

    Arguments:
        y_true (pd.Series): True labels.
        y_pred (pd.Series): Predicted values.

    Returns:
       pd.Series
    """
    return np.abs(y_true - y_pred)


def cross_entropy(y_true, y_pred_proba):
    """Computes Cross Entropy Loss per data point for classification problems.

    Arguments:
        y_true (pd.Series): True labels encoded as ints.
        y_pred_proba (pd.DataFrame): Predicted probabilities. One column per class.

    Returns:
       pd.Series
    """
    n_data_points = y_pred_proba.shape[0]
    log_likelihood = -np.log(y_pred_proba.values[range(n_data_points), y_true.values.astype("int")])
    return pd.Series(log_likelihood)


DEFAULT_METRICS = {ProblemTypes.BINARY: cross_entropy,
                   ProblemTypes.MULTICLASS: cross_entropy,
                   ProblemTypes.REGRESSION: abs_error}


def explain_predictions(pipeline, input_features, training_data=None, top_k_features=3, include_shap_values=False,
                        output_format="text"):
    """Creates a report summarizing the top contributing features for each data point in the input features.

    XGBoost models and CatBoost multiclass classifiers are not currently supported.

    Arguments:
        pipeline (PipelineBase): Fitted pipeline whose predictions we want to explain with SHAP.
        input_features (pd.DataFrame): Dataframe of input data to evaluate the pipeline on.
        training_data (pd.DataFrame): Dataframe of data the pipeline was fit on. This can be omitted for pipelines
            with tree-based estimators.
        top_k_features (int): How many of the highest/lowest contributing feature to include in the table for each
            data point.
        include_shap_values (bool): Whether SHAP values should be included in the table. Default is False.
        output_format (str): Either "text" or "dict". Default is "text".

    Returns:
        str or dict - A report explaining the top contributing features to each prediction for each row of input_features.
            The report will include the feature names, prediction contribution, and SHAP Value (optional).
    """
    if not (isinstance(input_features, pd.DataFrame) and not input_features.empty):
        raise ValueError("Parameter input_features must be a non-empty dataframe.")
    if output_format not in {"text", "dict"}:
        raise ValueError(f"Parameter output_format must be either text or dict. Received {output_format}")
    data = _ReportData(pipeline, input_features, y_true=None, y_pred=None,
                       y_pred_values=None, errors=None, index_list=range(input_features.shape[0]), metric=None)

    report_creator = _report_creator_factory(data, report_type="explain_predictions",
                                             output_format=output_format, top_k_features=top_k_features,
                                             include_shap_values=include_shap_values)
    return report_creator(data)


def explain_predictions_best_worst(pipeline, input_features, y_true, num_to_explain=5, top_k_features=3,
                                   include_shap_values=False, metric=None, output_format="text"):
    """Creates a report summarizing the top contributing features for the best and worst points in the dataset as measured by error to true labels.

    XGBoost models and CatBoost multiclass classifiers are not currently supported.

    Arguments:
        pipeline (PipelineBase): Fitted pipeline whose predictions we want to explain with SHAP.
        input_features (pd.DataFrame): Dataframe of input data to evaluate the pipeline on.
        y_true (pd.Series): True labels for the input data.
        num_to_explain (int): How many of the best, worst, random data points to explain.
        top_k_features (int): How many of the highest/lowest contributing feature to include in the table for each
            data point.
        include_shap_values (bool): Whether SHAP values should be included in the table. Default is False.
        metric (callable): The metric used to identify the best and worst points in the dataset. Function must accept
            the true labels and predicted value or probabilities as the only arguments and lower values
            must be better. By default, this will be the absolute error for regression problems and cross entropy loss
            for classification problems.
        output_format (str): Either "text" or "dict". Default is "text".

    Returns:
        str or dict - A report explaining the top contributing features for the best/worst predictions in the input_features.
            For each of the best/worst rows of input_features, the predicted values, true labels, metric value,
            feature names, prediction contribution, and SHAP Value (optional) will be listed.
    """
    if not (isinstance(input_features, pd.DataFrame) and input_features.shape[0] >= num_to_explain * 2):
        raise ValueError(f"Input features must be a dataframe with more than {num_to_explain * 2} rows! "
                         "Convert to a dataframe and select a smaller value for num_to_explain if you do not have "
                         "enough data.")
    if not isinstance(y_true, pd.Series):
        raise ValueError("Parameter y_true must be a pd.Series.")
    if y_true.shape[0] != input_features.shape[0]:
        raise ValueError("Parameters y_true and input_features must have the same number of data points. Received: "
                         f"true labels: {y_true.shape[0]} and {input_features.shape[0]}")
    if output_format not in {"text", "dict"}:
        raise ValueError(f"Parameter output_format must be either text or dict. Received {output_format}")
    if not metric:
        metric = DEFAULT_METRICS[pipeline.problem_type]

    try:
        if pipeline.problem_type == ProblemTypes.REGRESSION:
            y_pred = pipeline.predict(input_features)
            y_pred_values = None
            errors = metric(y_true, y_pred)
        else:
            y_pred = pipeline.predict_proba(input_features)
            y_pred_values = pipeline.predict(input_features)
            errors = metric(pipeline._encode_targets(y_true), y_pred)
    except Exception as e:
        tb = traceback.format_tb(sys.exc_info()[2])
        raise PipelineScoreError(exceptions={metric.__name__: (e, tb)}, scored_successfully={})

    sorted_scores = errors.sort_values()
    best = sorted_scores.index[:num_to_explain]
    worst = sorted_scores.index[-num_to_explain:]
    index_list = best.tolist() + worst.tolist()

    data = _ReportData(pipeline, input_features, y_true, y_pred, y_pred_values, errors, index_list, metric)

    report_creator = _report_creator_factory(data, report_type="explain_predictions_best_worst",
                                             output_format=output_format, top_k_features=top_k_features,
                                             include_shap_values=include_shap_values, num_to_explain=num_to_explain)
    return report_creator(data)


def clean_format_tree(clf):
    """Return data for a fitted tree in a restructured format

    Arguments:
        clf (ComponentBase): A fitted tree-based estimator.

    Returns:
        OrderedDict: An OrderedDict of OrderedDicts describing a tree structure
    """
    if not clf.model_family == ModelFamily.DECISION_TREE:
        raise ValueError("Tree structure reformatting is not supported for non-Tree estimators")
    est = clf._component_obj

    num_nodes = est.tree_.node_count
    children_left = est.tree_.children_left
    children_right = est.tree_.children_right
    features = est.tree_.feature
    thresholds = est.tree_.threshold
    values = est.tree_.value

    node_depth = np.zeros(shape=num_nodes, dtype=np.int64)
    is_leaves = np.zeros(shape=num_nodes, dtype=bool)
    stack = [(0, -1)]
    # Using sklearn's "Understanding the decision tree structure"
    while len(stack) > 0:
        node_id, parent_depth = stack.pop()
        node_depth[node_id] = parent_depth + 1

        if children_left[node_id] != children_right[node_id]:
            stack.append((children_left[node_id], parent_depth + 1))
            stack.append((children_right[node_id], parent_depth + 1))
        else:
            is_leaves[node_id] = True

    def recurse(i):
        if is_leaves[i]:
            return {'Name': f'Leaf_{i}'}
        return OrderedDict({
            'Name': f'Node_{i}',
            'Feature': features[i],
            'Threshold': thresholds[i],
            'Value': values[i],
            'Left_Child': recurse(children_left[i]),
            'Right_Child': recurse(children_right[i])
        })

    return recurse(0)

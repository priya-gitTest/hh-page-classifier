from collections import defaultdict, namedtuple
from functools import partial
import logging
import multiprocessing
from typing import List, Dict

from eli5.sklearn.explain_weights import explain_weights
import html_text
import numpy as np
from sklearn.cross_validation import LabelKFold, KFold
from sklearn.externals import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegressionCV, SGDClassifier
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
import tldextract


ModelMeta = namedtuple('ModelMeta', 'model, meta')


def train_model(docs: List[Dict], fit_clf=None) -> ModelMeta:
    """ Train and evaluate a model.
    docs is a list of dicts:
    {'url': url, 'html': html, 'relevant': True/False/None}.
    Return the model itself and a human-readable description of it's performance.
    """
    fit_clf = fit_clf or default_fit_clf
    if not docs:
        return ModelMeta(
            model=None, meta='Can not train a model: no pages given.')
    with_labels = [doc for doc in docs if doc.get('relevant') in [True, False]]
    if not with_labels:
        return ModelMeta(
            model=None, meta='Can not train a model: no labeled pages given.')

    all_ys = np.array([doc['relevant'] for doc in with_labels])
    classes = np.unique(all_ys)
    if len(classes) == 1:
        only_cls = classes[0]
        class_names = ['not relevant', 'relevant']
        return ModelMeta(
            model=None,
            meta='Can not train a model. Only {} pages in sample: '
                 'need examples of {} pages too.'.format(
                    class_names[only_cls], class_names[not only_cls]))

    logging.info('Extracting text')
    with multiprocessing.Pool() as pool:
        all_xs = pool.map(html_text.extract_text,
                          [doc['html'] for doc in with_labels],
                          chunksize=100)

    logging.info('Training and evaluating model')
    metrics = defaultdict(list)
    domains = [get_domain(doc['url']) for doc in with_labels]
    n_domains = len(set(domains))
    n_folds = 4
    descr = []
    if n_domains == 1:
        descr += [
            'Warning: only 1 domain in data means that it\'s impossible to do '
            'cross-validation across domains, '
            'and might result in model over-fitting.']
        folds = KFold(len(all_xs), n_folds=n_folds)
    else:
        folds = LabelKFold(domains, n_folds=min(n_domains, n_folds))
        if n_domains < n_folds:
            descr += [
                'Warning: low number of domains (just {}) '
                'might result in model over-fitting.'.format(n_domains)]
    folds = [fold for fold in folds if len(np.unique(all_ys[fold[0]])) > 1]
    with multiprocessing.Pool() as pool:
        clf_future = pool.apply_async(fit_clf, args=(all_xs, all_ys))
        if folds:
            for _metrics in pool.imap_unordered(
                    partial(eval_on_fold,
                            all_xs=all_xs, all_ys=all_ys, fit_clf=fit_clf),
                    folds):
                for k, v in _metrics.items():
                    metrics[k].append(v)
        else:
            descr += [
                'Warning: Can not do cross-validation, as there are no folds where '
                'training data has both relevant and non-relevant examples. '
                'There are too few domains or the dataset is too unbalanced.']
        clf = clf_future.get()

    descr.extend(describe_model(clf, metrics, docs, with_labels, n_domains))
    meta = '\n'.join(descr)
    logging.info('Model meta:\n{}'.format(meta))
    return ModelMeta(model=clf, meta=meta)


def default_fit_clf(xs, ys) -> Pipeline:
    # Doing explicit feature selection because:
    # - eli5 does not support pipelines with feature selection
    # - final model should be small and does not need the whole vocabulary
    vec = TfidfVectorizer()
    transformed = vec.fit_transform(xs)
    feature_selection_clf = SGDClassifier(
        loss='log', penalty='l2', n_iter=50, random_state=42)
    feature_selection_clf.fit(transformed, ys)
    abs_coefs = np.abs(feature_selection_clf.coef_[0])
    features = set((abs_coefs > np.mean(abs_coefs)).nonzero()[0])
    # FIXME - relies on ngram_range=(1, 1) ?
    vocabulary = [w for w, idx in vec.vocabulary_.items() if idx in features]
    clf = Pipeline([
        ('vec', TfidfVectorizer(vocabulary=vocabulary)),
        ('clf', LogisticRegressionCV(random_state=42)),
    ])
    clf.fit(xs, ys)
    return clf


def eval_on_fold(fold, all_xs, all_ys, fit_clf) -> Dict:
    """ Train and evaluate the classifier on a given fold.
    """
    train_idx, test_idx = fold
    clf = fit_clf(flt_list(all_xs, train_idx), all_ys[train_idx])
    test_xs, test_ys = flt_list(all_xs, test_idx), all_ys[test_idx]
    pred_ys_prob = clf.predict_proba(test_xs)[:, 1]
    pred_ys = clf.predict(test_xs)
    try:
        auc = roc_auc_score(test_ys, pred_ys_prob)
    except ValueError:
        auc = float('nan')
    return {
        'Accuracy': accuracy_score(test_ys, pred_ys),
        'F1': f1_score(test_ys, pred_ys),
        'ROC AUC': auc,
    }


def flt_list(lst: List, indices: np.ndarray) -> List:
    # to avoid creating a big numpy array, filter the list
    indices = set(indices)
    return [x for i, x in enumerate(lst) if i in indices]


def describe_model(
        clf: Pipeline, metrics: Dict,
        docs: List[Dict], with_labels: List[Dict], n_domains: int) -> List[str]:
    """ Return a human-readable model description.
    """
    descr = []
    descr += [
        'Dataset: {n_docs} documents, {labeled_ratio:.0%} with labels '
        'across {n_domains} domain{s}.'.format(
            n_docs=len(docs),
            labeled_ratio=len(with_labels) / len(docs),
            n_domains=n_domains,
            s='s' if n_domains > 1 else '',
        )]
    relevant = [doc for doc in docs if doc['relevant']]
    relevant_ratio = len(relevant) / len(with_labels)
    descr += ['Class balance: {:.0%} relevant, {:.0%} not relevant.'
                  .format(relevant_ratio, 1. - relevant_ratio)]
    if metrics:
        descr += ['Metrics:']
        aggr_metrics = {
            k: '  {:.3f} ± {:.3f}'.format(np.mean(v), 1.96 * np.std(v))
            for k, v in metrics.items()}
        descr += ['{:<20}: {}'.format(k, v)
                  for k, v in sorted(aggr_metrics.items())]
    weights_explanation = explain_weights(
        clf.named_steps['clf'], vec=clf.named_steps['vec'], top=10)
    feature_weights = weights_explanation['classes'][0]['feature_weights']
    descr.extend(features_descr(feature_weights, 'pos', 'Positive'))
    descr.extend(features_descr(feature_weights, 'neg', 'Negative'))
    # TODO - some advice: are metrics good or bad, how is the class balance
    return descr


def features_descr(feature_weights, key, key_name):
    rem_key = '{}_remaining'.format(key)
    descr = []
    if key in feature_weights or rem_key in feature_weights:
        descr += ['{} features:'.format(key_name)]
        descr.extend('{:<20}: {:.2f}'.format(feature, weight)
                     for feature, weight in feature_weights.get(key, []))
        remaining = feature_weights.get(rem_key)
        if remaining:
            descr += ['Other {} features: {}'.format(key_name.lower(), remaining)]
    return descr


def get_domain(url: str) -> str:
    return tldextract.extract(url).registered_domain.lower()


def main():
    import argparse
    import json
    import time
    from .utils import configure_logging
    from .service import encode_model

    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument('message_filename')
    args = parser.parse_args()
    with open(args.message_filename) as f:
        logging.info('Decoding message')
        message = json.load(f)
    logging.info('Done, starting train_model')
    t0 = time.time()
    result = train_model(message['pages'])
    logging.info('Training took {:.1f} s'.format(time.time() - t0))
    logging.info('Model size: {:,} bytes'.format(len(encode_model(result.model))))

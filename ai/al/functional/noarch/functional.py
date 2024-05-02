'''
    Helper snippets for built-in AL heuristics on computing the priority score.

    2019-24 Benjamin Kellenberger
'''

from typing import Iterable
import numpy as np



def _breaking_ties(prediction: dict) -> dict:
    '''
        Computes the Breaking Ties heuristic (Luo et al. 2005: "Active Learning to Recognize
        Multiple Types of Plankton." JMLR 6, 589-613.)

        In case of segmentation masks, the average BT value is returned.
    '''
    bt_val = None
    if 'logits' in prediction:
        logits = np.array(prediction['logits'].copy())

        if logits.ndim == 3:
            # spatial prediction
            logits = np.sort(logits, 0)
            bt_val = 1 - np.mean(logits[-1,...] - logits[-2,...])
        else:
            logits = np.sort(logits)
            bt_val = 1 - (logits[-1] - logits[-2])
    if isinstance(bt_val, np.ndarray):
        # criterion across multiple inputs (e.g., segmentation mask): take average
        bt_val = np.mean(bt_val)
        # btVal = btVal.tolist()
    return bt_val



def _max_confidence(prediction: dict) -> dict:
    '''
        Returns the maximum value of the logits as a priority value.
    '''
    if 'logits' in prediction:
        if isinstance(prediction['logits'], Iterable):
            max_val = max(prediction['logits'])
        else:
            try:
                max_val = float(prediction['logits'])
            except Exception:
                max_val = None
    elif 'confidence' in prediction:
        if isinstance(prediction['confidence'], Iterable):
            max_val = max(prediction['confidence'])
        else:
            try:
                max_val = float(prediction['confidence'])
            except Exception:
                max_val = None
    else:
        max_val = None

    if isinstance(max_val, np.ndarray):
        # criterion across multiple inputs (e.g., segmentation mask): take maximum
        max_val = np.max(max_val)
        # max_val = max_val.tolist()
    return max_val

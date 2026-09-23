"""Reviewed, verbatim calculate function from native experience_store.py."""
def calculate(operation,values):
    import math
    if operation not in {'sum','mean','min','max','range'}:raise ValueError('Unsupported data operation')
    if not isinstance(values,list) or not 1<=len(values)<=4096 or any(type(v) not in (float,int) or not math.isfinite(v) or abs(v)>1e100 for v in values):
        raise ValueError('Bounded finite numeric list required')
    result={'sum':lambda:math.fsum(values),'mean':lambda:math.fsum(values)/len(values),
        'min':lambda:min(values),'max':lambda:max(values),'range':lambda:max(values)-min(values)}[operation]()
    return result

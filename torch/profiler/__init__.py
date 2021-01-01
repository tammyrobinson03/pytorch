# type: ignore
r'''
PyTorch Profiler is a tool that allows the collecton of the performance metrics during the training and inference.
Profiler's context manager API can be used to better understand what model operators are the most expensive,
examine their input shapes and stack traces, study device kernel activity and visualize the execution trace.

.. note::
    An earlier version of the API in ``torch.autograd`` module is considered legacy and will be deprecated.

'''

from .profiler import profile, schedule, ProfilerAction, ProfilerActivity

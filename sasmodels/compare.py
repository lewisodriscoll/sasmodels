#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Program to compare models using different compute engines.

This program lets you compare results between OpenCL and DLL versions
of the code and between precision (half, fast, single, double, quad),
where fast precision is single precision using native functions for
trig, etc., and may not be completely IEEE 754 compliant.  This lets
make sure that the model calculations are stable, or if you need to
tag the model as double precision only.

Run using ./compare.sh (Linux, Mac) or compare.bat (Windows) in the
sasmodels root to see the command line options.

Note that there is no way within sasmodels to select between an
OpenCL CPU device and a GPU device, but you can do so by setting the
PYOPENCL_CTX environment variable ahead of time.  Start a python
interpreter and enter::

    import pyopencl as cl
    cl.create_some_context()

This will prompt you to select from the available OpenCL devices
and tell you which string to use for the PYOPENCL_CTX variable.
On Windows you will need to remove the quotes.
"""

from __future__ import print_function

import sys
import os
import math
import datetime
import traceback
import re

import numpy as np  # type: ignore

from . import core
from . import kerneldll
from . import exception
from .data import plot_theory, empty_data1D, empty_data2D, load_data
from .direct_model import DirectModel
from .convert import revert_name, revert_pars, constrain_new_to_old
from .generate import FLOAT_RE

try:
    from typing import Optional, Dict, Any, Callable, Tuple
except Exception:
    pass
else:
    from .modelinfo import ModelInfo, Parameter, ParameterSet
    from .data import Data
    Calculator = Callable[[float], np.ndarray]

USAGE = """
usage: sascomp model [options...] [key=val]

Generate and compare SAS models.  If a single model is specified it shows
a plot of that model.  Different models can be compared, or the same model
with different parameters.  The same model with the same parameters can
be compared with different calculation engines to see the effects of precision
on the resultant values.

model or model1,model2 are the names of the models to compare (see below).

Options (* for default):

    === data generation ===
    -data="path" uses q, dq from the data file
    -noise=0 sets the measurement error dI/I
    -res=0 sets the resolution width dQ/Q if calculating with resolution
    -lowq*/-midq/-highq/-exq use q values up to 0.05, 0.2, 1.0, 10.0
    -nq=128 sets the number of Q points in the data set
    -1d*/-2d computes 1d or 2d data
    -zero indicates that q=0 should be included

    === model parameters ===
    -preset*/-random[=seed] preset or random parameters
    -sets=n generates n random datasets with the seed given by -random=seed
    -pars/-nopars* prints the parameter set or not
    -default/-demo* use demo vs default parameters

    === calculation options ===
    -mono*/-poly force monodisperse or allow polydisperse demo parameters
    -cutoff=1e-5* cutoff value for including a point in polydispersity
    -magnetic/-nonmagnetic* suppress magnetism
    -accuracy=Low accuracy of the resolution calculation Low, Mid, High, Xhigh
    -neval=1 sets the number of evals for more accurate timing

    === precision options ===
    -calc=default uses the default calcution precision
    -single/-double/-half/-fast sets an OpenCL calculation engine
    -single!/-double!/-quad! sets an OpenMP calculation engine
    -sasview sets the sasview calculation engine

    === plotting ===
    -plot*/-noplot plots or suppress the plot of the model
    -linear/-log*/-q4 intensity scaling on plots
    -hist/-nohist* plot histogram of relative error
    -abs/-rel* plot relative or absolute error
    -title="note" adds note to the plot title, after the model name

    === output options ===
    -edit starts the parameter explorer
    -help/-html shows the model docs instead of running the model

The interpretation of quad precision depends on architecture, and may
vary from 64-bit to 128-bit, with 80-bit floats being common (1e-19 precision).
On unix and mac you may need single quotes around the DLL computation
engines, such as -calc='single!,double!' since !, is treated as a history
expansion request in the shell.

Key=value pairs allow you to set specific values for the model parameters.
Key=value1,value2 to compare different values of the same parameter. The
value can be an expression including other parameters.

Items later on the command line override those that appear earlier.

Examples:

    # compare single and double precision calculation for a barbell
    sascomp barbell -calc=single,double

    # generate 10 random lorentz models, with seed=27
    sascomp lorentz -sets=10 -seed=27

    # compare ellipsoid with R = R_polar = R_equatorial to sphere of radius R
    sascomp sphere,ellipsoid radius_polar=radius radius_equatorial=radius

    # model timing test requires multiple evals to perform the estimate
    sascomp pringle -calc=single,double -timing=100,100 -noplot
"""

# Update docs with command line usage string.   This is separate from the usual
# doc string so that we can display it at run time if there is an error.
# lin
__doc__ = (__doc__  # pylint: disable=redefined-builtin
           + """
Program description
-------------------

""" + USAGE)

kerneldll.ALLOW_SINGLE_PRECISION_DLLS = True

# list of math functions for use in evaluating parameters
MATH = dict((k,getattr(math, k)) for k in dir(math) if not k.startswith('_'))

# CRUFT python 2.6
if not hasattr(datetime.timedelta, 'total_seconds'):
    def delay(dt):
        """Return number date-time delta as number seconds"""
        return dt.days * 86400 + dt.seconds + 1e-6 * dt.microseconds
else:
    def delay(dt):
        """Return number date-time delta as number seconds"""
        return dt.total_seconds()


class push_seed(object):
    """
    Set the seed value for the random number generator.

    When used in a with statement, the random number generator state is
    restored after the with statement is complete.

    :Parameters:

    *seed* : int or array_like, optional
        Seed for RandomState

    :Example:

    Seed can be used directly to set the seed::

        >>> from numpy.random import randint
        >>> push_seed(24)
        <...push_seed object at...>
        >>> print(randint(0,1000000,3))
        [242082    899 211136]

    Seed can also be used in a with statement, which sets the random
    number generator state for the enclosed computations and restores
    it to the previous state on completion::

        >>> with push_seed(24):
        ...    print(randint(0,1000000,3))
        [242082    899 211136]

    Using nested contexts, we can demonstrate that state is indeed
    restored after the block completes::

        >>> with push_seed(24):
        ...    print(randint(0,1000000))
        ...    with push_seed(24):
        ...        print(randint(0,1000000,3))
        ...    print(randint(0,1000000))
        242082
        [242082    899 211136]
        899

    The restore step is protected against exceptions in the block::

        >>> with push_seed(24):
        ...    print(randint(0,1000000))
        ...    try:
        ...        with push_seed(24):
        ...            print(randint(0,1000000,3))
        ...            raise Exception()
        ...    except Exception:
        ...        print("Exception raised")
        ...    print(randint(0,1000000))
        242082
        [242082    899 211136]
        Exception raised
        899
    """
    def __init__(self, seed=None):
        # type: (Optional[int]) -> None
        self._state = np.random.get_state()
        np.random.seed(seed)

    def __enter__(self):
        # type: () -> None
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        # type: (Any, BaseException, Any) -> None
        # TODO: better typing for __exit__ method
        np.random.set_state(self._state)

def tic():
    # type: () -> Callable[[], float]
    """
    Timer function.

    Use "toc=tic()" to start the clock and "toc()" to measure
    a time interval.
    """
    then = datetime.datetime.now()
    return lambda: delay(datetime.datetime.now() - then)


def set_beam_stop(data, radius, outer=None):
    # type: (Data, float, float) -> None
    """
    Add a beam stop of the given *radius*.  If *outer*, make an annulus.

    Note: this function does not require sasview
    """
    if hasattr(data, 'qx_data'):
        q = np.sqrt(data.qx_data**2 + data.qy_data**2)
        data.mask = (q < radius)
        if outer is not None:
            data.mask |= (q >= outer)
    else:
        data.mask = (data.x < radius)
        if outer is not None:
            data.mask |= (data.x >= outer)


def parameter_range(p, v):
    # type: (str, float) -> Tuple[float, float]
    """
    Choose a parameter range based on parameter name and initial value.
    """
    # process the polydispersity options
    if p.endswith('_pd_n'):
        return 0., 100.
    elif p.endswith('_pd_nsigma'):
        return 0., 5.
    elif p.endswith('_pd_type'):
        raise ValueError("Cannot return a range for a string value")
    elif any(s in p for s in ('theta', 'phi', 'psi')):
        # orientation in [-180,180], orientation pd in [0,45]
        if p.endswith('_pd'):
            return 0., 45.
        else:
            return -180., 180.
    elif p.endswith('_pd'):
        return 0., 1.
    elif 'sld' in p:
        return -0.5, 10.
    elif p == 'background':
        return 0., 10.
    elif p == 'scale':
        return 0., 1.e3
    elif v < 0.:
        return 2.*v, -2.*v
    else:
        return 0., (2.*v if v > 0. else 1.)


def _randomize_one(model_info, name, value):
    # type: (ModelInfo, str, float) -> float
    # type: (ModelInfo, str, str) -> str
    """
    Randomize a single parameter.
    """
    # Set the amount of polydispersity/angular dispersion, but by default pd_n
    # is zero so there is no polydispersity.  This allows us to turn on/off
    # pd by setting pd_n, and still have randomly generated values
    if name.endswith('_pd'):
        par = model_info.parameters[name[:-3]]
        if par.type == 'orientation':
            # Let oriention variation peak around 13 degrees; 95% < 42 degrees
            return 180*np.random.beta(2.5, 20)
        else:
            # Let polydispersity peak around 15%; 95% < 0.4; max=100%
            return np.random.beta(1.5, 7)

    # pd is selected globally rather than per parameter, so set to 0 for no pd
    # In particular, when multiple pd dimensions, want to decrease the number
    # of points per dimension for faster computation
    if name.endswith('_pd_n'):
        return 0

    # Don't mess with distribution type for now
    if name.endswith('_pd_type'):
        return 'gaussian'

    # type-dependent value of number of sigmas; for gaussian use 3.
    if name.endswith('_pd_nsigma'):
        return 3.

    # background in the range [0.01, 1]
    if name == 'background':
        return 10**np.random.uniform(-2, 0)

    # scale defaults to 0.1% to 30% volume fraction
    if name == 'scale':
        return 10**np.random.uniform(-3, -0.5)

    # If it is a list of choices, pick one at random with equal probability
    # In practice, the model specific random generator will override.
    par = model_info.parameters[name]
    if len(par.limits) > 2:  # choice list
        return np.random.randint(len(par.limits))

    # If it is a fixed range, pick from it with equal probability.
    # For logarithmic ranges, the model will have to override.
    if np.isfinite(par.limits).all():
        return np.random.uniform(*par.limits)

    # If the paramter is marked as an sld use the range of neutron slds
    # TODO: ought to randomly contrast match a pair of SLDs
    if par.type == 'sld':
        return np.random.uniform(-0.5, 12)

    # Limit magnetic SLDs to a smaller range, from zero to iron=5/A^2
    if par.name.startswith('M0:'):
        return np.random.uniform(0, 5)

    # Guess at the random length/radius/thickness.  In practice, all models
    # are going to set their own reasonable ranges.
    if par.type == 'volume':
        if ('length' in par.name or
                'radius' in par.name or
                'thick' in par.name):
            return 10**np.random.uniform(2, 4)

    # In the absence of any other info, select a value in [0, 2v], or
    # [-2|v|, 2|v|] if v is negative, or [0, 1] if v is zero.  Mostly the
    # model random parameter generators will override this default.
    low, high = parameter_range(par.name, value)
    limits = (max(par.limits[0], low), min(par.limits[1], high))
    return np.random.uniform(*limits)

def _random_pd(model_info, pars):
    pd = [p for p in model_info.parameters.kernel_parameters if p.polydisperse]
    pd_volume = []
    pd_oriented = []
    for p in pd:
        if p.type == 'orientation':
            pd_oriented.append(p.name)
        elif p.length_control is not None:
            n = int(pars.get(p.length_control, 1) + 0.5)
            pd_volume.extend(p.name+str(k+1) for k in range(n))
        elif p.length > 1:
            pd_volume.extend(p.name+str(k+1) for k in range(p.length))
        else:
            pd_volume.append(p.name)
    u = np.random.rand()
    n = len(pd_volume)
    if u < 0.01 or n < 1:
        pass  # 1% chance of no polydispersity
    elif u < 0.86 or n < 2:
        pars[np.random.choice(pd_volume)+"_pd_n"] = 35
    elif u < 0.99 or n < 3:
        choices = np.random.choice(len(pd_volume), size=2)
        pars[pd_volume[choices[0]]+"_pd_n"] = 25
        pars[pd_volume[choices[1]]+"_pd_n"] = 10
    else:
        choices = np.random.choice(len(pd_volume), size=3)
        pars[pd_volume[choices[0]]+"_pd_n"] = 25
        pars[pd_volume[choices[1]]+"_pd_n"] = 10
        pars[pd_volume[choices[2]]+"_pd_n"] = 5
    if pd_oriented:
        pars['theta_pd_n'] = 20
        if np.random.rand() < 0.1:
            pars['phi_pd_n'] = 5
        if np.random.rand() < 0.1:
            if any(p.name == 'psi' for p in model_info.parameters.kernel_parameters):
                #print("generating psi_pd_n")
                pars['psi_pd_n'] = 5

    ## Show selected polydispersity
    #for name, value in pars.items():
    #    if name.endswith('_pd_n') and value > 0:
    #        print(name, value, pars.get(name[:-5], 0), pars.get(name[:-2], 0))


def randomize_pars(model_info, pars):
    # type: (ModelInfo, ParameterSet) -> ParameterSet
    """
    Generate random values for all of the parameters.

    Valid ranges for the random number generator are guessed from the name of
    the parameter; this will not account for constraints such as cap radius
    greater than cylinder radius in the capped_cylinder model, so
    :func:`constrain_pars` needs to be called afterward..
    """
    # Note: the sort guarantees order of calls to random number generator
    random_pars = dict((p, _randomize_one(model_info, p, v))
                       for p, v in sorted(pars.items()))
    if model_info.random is not None:
        random_pars.update(model_info.random())
    _random_pd(model_info, random_pars)
    return random_pars


def constrain_pars(model_info, pars):
    # type: (ModelInfo, ParameterSet) -> None
    """
    Restrict parameters to valid values.

    This includes model specific code for models such as capped_cylinder
    which need to support within model constraints (cap radius more than
    cylinder radius in this case).

    Warning: this updates the *pars* dictionary in place.
    """
    # TODO: move the model specific code to the individual models
    name = model_info.id
    # if it is a product model, then just look at the form factor since
    # none of the structure factors need any constraints.
    if '*' in name:
        name = name.split('*')[0]

    # Suppress magnetism for python models (not yet implemented)
    if callable(model_info.Iq):
        pars.update(suppress_magnetism(pars))

    if name == 'barbell':
        if pars['radius_bell'] < pars['radius']:
            pars['radius'], pars['radius_bell'] = pars['radius_bell'], pars['radius']

    elif name == 'capped_cylinder':
        if pars['radius_cap'] < pars['radius']:
            pars['radius'], pars['radius_cap'] = pars['radius_cap'], pars['radius']

    elif name == 'guinier':
        # Limit guinier to an Rg such that Iq > 1e-30 (single precision cutoff)
        # I(q) = A e^-(Rg^2 q^2/3) > e^-(30 ln 10)
        # => ln A - (Rg^2 q^2/3) > -30 ln 10
        # => Rg^2 q^2/3 < 30 ln 10 + ln A
        # => Rg < sqrt(90 ln 10 + 3 ln A)/q
        #q_max = 0.2  # mid q maximum
        q_max = 1.0  # high q maximum
        rg_max = np.sqrt(90*np.log(10) + 3*np.log(pars['scale']))/q_max
        pars['rg'] = min(pars['rg'], rg_max)

    elif name == 'pearl_necklace':
        if pars['radius'] < pars['thick_string']:
            pars['radius'], pars['thick_string'] = pars['thick_string'], pars['radius']
        pass

    elif name == 'rpa':
        # Make sure phi sums to 1.0
        if pars['case_num'] < 2:
            pars['Phi1'] = 0.
            pars['Phi2'] = 0.
        elif pars['case_num'] < 5:
            pars['Phi1'] = 0.
        total = sum(pars['Phi'+c] for c in '1234')
        for c in '1234':
            pars['Phi'+c] /= total

def parlist(model_info, pars, is2d):
    # type: (ModelInfo, ParameterSet, bool) -> str
    """
    Format the parameter list for printing.
    """
    lines = []
    parameters = model_info.parameters
    magnetic = False
    magnetic_pars = []
    for p in parameters.user_parameters(pars, is2d):
        if any(p.id.startswith(x) for x in ('M0:', 'mtheta:', 'mphi:')):
            continue
        if p.id.startswith('up:'):
            magnetic_pars.append("%s=%s"%(p.id, pars.get(p.id, p.default)))
            continue
        fields = dict(
            value=pars.get(p.id, p.default),
            pd=pars.get(p.id+"_pd", 0.),
            n=int(pars.get(p.id+"_pd_n", 0)),
            nsigma=pars.get(p.id+"_pd_nsgima", 3.),
            pdtype=pars.get(p.id+"_pd_type", 'gaussian'),
            relative_pd=p.relative_pd,
            M0=pars.get('M0:'+p.id, 0.),
            mphi=pars.get('mphi:'+p.id, 0.),
            mtheta=pars.get('mtheta:'+p.id, 0.),
        )
        lines.append(_format_par(p.name, **fields))
        magnetic = magnetic or fields['M0'] != 0.
    if magnetic and magnetic_pars:
        lines.append(" ".join(magnetic_pars))
    return "\n".join(lines)

    #return "\n".join("%s: %s"%(p, v) for p, v in sorted(pars.items()))

def _format_par(name, value=0., pd=0., n=0, nsigma=3., pdtype='gaussian',
                relative_pd=False, M0=0., mphi=0., mtheta=0.):
    # type: (str, float, float, int, float, str) -> str
    line = "%s: %g"%(name, value)
    if pd != 0.  and n != 0:
        if relative_pd:
            pd *= value
        line += " +/- %g  (%d points in [-%g,%g] sigma %s)"\
                % (pd, n, nsigma, nsigma, pdtype)
    if M0 != 0.:
        line += "  M0:%.3f  mphi:%.1f  mtheta:%.1f" % (M0, mphi, mtheta)
    return line

def suppress_pd(pars, suppress=True):
    # type: (ParameterSet) -> ParameterSet
    """
    If suppress is True complete eliminate polydispersity of the model to test
    models more quickly.  If suppress is False, make sure at least one
    parameter is polydisperse, setting the first polydispersity parameter to
    15% if no polydispersity is given (with no explicit demo parameters given
    in the model, there will be no default polydispersity).
    """
    pars = pars.copy()
    #print("pars=", pars)
    if suppress:
        for p in pars:
            if p.endswith("_pd_n"):
                pars[p] = 0
    else:
        any_pd = False
        first_pd = None
        for p in pars:
            if p.endswith("_pd_n"):
                pd = pars.get(p[:-2], 0.)
                any_pd |= (pars[p] != 0 and pd != 0.)
                if first_pd is None:
                    first_pd = p
        if not any_pd and first_pd is not None:
            if pars[first_pd] == 0:
                pars[first_pd] = 35
            if first_pd[:-2] not in pars or pars[first_pd[:-2]] == 0:
                pars[first_pd[:-2]] = 0.15
    return pars

def suppress_magnetism(pars, suppress=True):
    # type: (ParameterSet) -> ParameterSet
    """
    If suppress is True complete eliminate magnetism of the model to test
    models more quickly.  If suppress is False, make sure at least one sld
    parameter is magnetic, setting the first parameter to have a strong
    magnetic sld (8/A^2) at 60 degrees (with no explicit demo parameters given
    in the model, there will be no default magnetism).
    """
    pars = pars.copy()
    if suppress:
        for p in pars:
            if p.startswith("M0:"):
                pars[p] = 0
    else:
        any_mag = False
        first_mag = None
        for p in pars:
            if p.startswith("M0:"):
                any_mag |= (pars[p] != 0)
                if first_mag is None:
                    first_mag = p
        if not any_mag and first_mag is not None:
            pars[first_mag] = 8.
    return pars

def eval_sasview(model_info, data):
    # type: (Modelinfo, Data) -> Calculator
    """
    Return a model calculator using the pre-4.0 SasView models.
    """
    # importing sas here so that the error message will be that sas failed to
    # import rather than the more obscure smear_selection not imported error
    import sas
    import sas.models
    from sas.models.qsmearing import smear_selection
    from sas.models.MultiplicationModel import MultiplicationModel
    from sas.models.dispersion_models import models as dispersers

    def get_model_class(name):
        # type: (str) -> "sas.models.BaseComponent"
        #print("new",sorted(_pars.items()))
        __import__('sas.models.' + name)
        ModelClass = getattr(getattr(sas.models, name, None), name, None)
        if ModelClass is None:
            raise ValueError("could not find model %r in sas.models"%name)
        return ModelClass

    # WARNING: ugly hack when handling model!
    # Sasview models with multiplicity need to be created with the target
    # multiplicity, so we cannot create the target model ahead of time for
    # for multiplicity models.  Instead we store the model in a list and
    # update the first element of that list with the new multiplicity model
    # every time we evaluate.

    # grab the sasview model, or create it if it is a product model
    if model_info.composition:
        composition_type, parts = model_info.composition
        if composition_type == 'product':
            P, S = [get_model_class(revert_name(p))() for p in parts]
            model = [MultiplicationModel(P, S)]
        else:
            raise ValueError("sasview mixture models not supported by compare")
    else:
        old_name = revert_name(model_info)
        if old_name is None:
            raise ValueError("model %r does not exist in old sasview"
                            % model_info.id)
        ModelClass = get_model_class(old_name)
        model = [ModelClass()]
    model[0].disperser_handles = {}

    # build a smearer with which to call the model, if necessary
    smearer = smear_selection(data, model=model)
    if hasattr(data, 'qx_data'):
        q = np.sqrt(data.qx_data**2 + data.qy_data**2)
        index = ((~data.mask) & (~np.isnan(data.data))
                 & (q >= data.qmin) & (q <= data.qmax))
        if smearer is not None:
            smearer.model = model  # because smear_selection has a bug
            smearer.accuracy = data.accuracy
            smearer.set_index(index)
            def _call_smearer():
                smearer.model = model[0]
                return smearer.get_value()
            theory = _call_smearer
        else:
            theory = lambda: model[0].evalDistribution([data.qx_data[index],
                                                        data.qy_data[index]])
    elif smearer is not None:
        theory = lambda: smearer(model[0].evalDistribution(data.x))
    else:
        theory = lambda: model[0].evalDistribution(data.x)

    def calculator(**pars):
        # type: (float, ...) -> np.ndarray
        """
        Sasview calculator for model.
        """
        oldpars = revert_pars(model_info, pars)
        # For multiplicity models, create a model with the correct multiplicity
        control = oldpars.pop("CONTROL", None)
        if control is not None:
            # sphericalSLD has one fewer multiplicity.  This update should
            # happen in revert_pars, but it hasn't been called yet.
            model[0] = ModelClass(control)
        # paying for parameter conversion each time to keep life simple, if not fast
        for k, v in oldpars.items():
            if k.endswith('.type'):
                par = k[:-5]
                if v == 'gaussian': continue
                cls = dispersers[v if v != 'rectangle' else 'rectangula']
                handle = cls()
                model[0].disperser_handles[par] = handle
                try:
                    model[0].set_dispersion(par, handle)
                except Exception:
                    exception.annotate_exception("while setting %s to %r"
                                                 %(par, v))
                    raise


        #print("sasview pars",oldpars)
        for k, v in oldpars.items():
            name_attr = k.split('.')  # polydispersity components
            if len(name_attr) == 2:
                par, disp_par = name_attr
                model[0].dispersion[par][disp_par] = v
            else:
                model[0].setParam(k, v)
        return theory()

    calculator.engine = "sasview"
    return calculator

DTYPE_MAP = {
    'half': '16',
    'fast': 'fast',
    'single': '32',
    'double': '64',
    'quad': '128',
    'f16': '16',
    'f32': '32',
    'f64': '64',
    'float16': '16',
    'float32': '32',
    'float64': '64',
    'float128': '128',
    'longdouble': '128',
}
def eval_opencl(model_info, data, dtype='single', cutoff=0.):
    # type: (ModelInfo, Data, str, float) -> Calculator
    """
    Return a model calculator using the OpenCL calculation engine.
    """
    if not core.HAVE_OPENCL:
        raise RuntimeError("OpenCL not available")
    model = core.build_model(model_info, dtype=dtype, platform="ocl")
    calculator = DirectModel(data, model, cutoff=cutoff)
    calculator.engine = "OCL%s"%DTYPE_MAP[str(model.dtype)]
    return calculator

def eval_ctypes(model_info, data, dtype='double', cutoff=0.):
    # type: (ModelInfo, Data, str, float) -> Calculator
    """
    Return a model calculator using the DLL calculation engine.
    """
    model = core.build_model(model_info, dtype=dtype, platform="dll")
    calculator = DirectModel(data, model, cutoff=cutoff)
    calculator.engine = "OMP%s"%DTYPE_MAP[str(model.dtype)]
    return calculator

def time_calculation(calculator, pars, evals=1):
    # type: (Calculator, ParameterSet, int) -> Tuple[np.ndarray, float]
    """
    Compute the average calculation time over N evaluations.

    An additional call is generated without polydispersity in order to
    initialize the calculation engine, and make the average more stable.
    """
    # initialize the code so time is more accurate
    if evals > 1:
        calculator(**suppress_pd(pars))
    toc = tic()
    # make sure there is at least one eval
    value = calculator(**pars)
    for _ in range(evals-1):
        value = calculator(**pars)
    average_time = toc()*1000. / evals
    #print("I(q)",value)
    return value, average_time

def make_data(opts):
    # type: (Dict[str, Any]) -> Tuple[Data, np.ndarray]
    """
    Generate an empty dataset, used with the model to set Q points
    and resolution.

    *opts* contains the options, with 'qmax', 'nq', 'res',
    'accuracy', 'is2d' and 'view' parsed from the command line.
    """
    qmax, nq, res = opts['qmax'], opts['nq'], opts['res']
    if opts['is2d']:
        q = np.linspace(-qmax, qmax, nq)  # type: np.ndarray
        data = empty_data2D(q, resolution=res)
        data.accuracy = opts['accuracy']
        set_beam_stop(data, 0.0004)
        index = ~data.mask
    else:
        if opts['view'] == 'log' and not opts['zero']:
            qmax = math.log10(qmax)
            q = np.logspace(qmax-3, qmax, nq)
        else:
            q = np.linspace(0.001*qmax, qmax, nq)
        if opts['zero']:
            q = np.hstack((0, q))
        data = empty_data1D(q, resolution=res)
        index = slice(None, None)
    return data, index

def make_engine(model_info, data, dtype, cutoff):
    # type: (ModelInfo, Data, str, float) -> Calculator
    """
    Generate the appropriate calculation engine for the given datatype.

    Datatypes with '!' appended are evaluated using external C DLLs rather
    than OpenCL.
    """
    if dtype == 'sasview':
        return eval_sasview(model_info, data)
    elif dtype is None or not dtype.endswith('!'):
        return eval_opencl(model_info, data, dtype=dtype, cutoff=cutoff)
    else:
        return eval_ctypes(model_info, data, dtype=dtype[:-1], cutoff=cutoff)

def _show_invalid(data, theory):
    # type: (Data, np.ma.ndarray) -> None
    """
    Display a list of the non-finite values in theory.
    """
    if not theory.mask.any():
        return

    if hasattr(data, 'x'):
        bad = zip(data.x[theory.mask], theory[theory.mask])
        print("   *** ", ", ".join("I(%g)=%g"%(x, y) for x, y in bad))


def compare(opts, limits=None):
    # type: (Dict[str, Any], Optional[Tuple[float, float]]) -> Tuple[float, float]
    """
    Preform a comparison using options from the command line.

    *limits* are the limits on the values to use, either to set the y-axis
    for 1D or to set the colormap scale for 2D.  If None, then they are
    inferred from the data and returned. When exploring using Bumps,
    the limits are set when the model is initially called, and maintained
    as the values are adjusted, making it easier to see the effects of the
    parameters.
    """
    limits = np.Inf, -np.Inf
    for k in range(opts['sets']):
        opts['pars'] = parse_pars(opts)
        if opts['pars'] is None:
            return
        result = run_models(opts, verbose=True)
        if opts['plot']:
            limits = plot_models(opts, result, limits=limits, setnum=k)
    if opts['plot']:
        import matplotlib.pyplot as plt
        plt.show()

def run_models(opts, verbose=False):
    # type: (Dict[str, Any]) -> Dict[str, Any]

    base, comp = opts['engines']
    base_n, comp_n = opts['count']
    base_pars, comp_pars = opts['pars']
    data = opts['data']

    comparison = comp is not None

    base_time = comp_time = None
    base_value = comp_value = resid = relerr = None

    # Base calculation
    try:
        base_raw, base_time = time_calculation(base, base_pars, base_n)
        base_value = np.ma.masked_invalid(base_raw)
        if verbose:
            print("%s t=%.2f ms, intensity=%.0f"
                  % (base.engine, base_time, base_value.sum()))
        _show_invalid(data, base_value)
    except ImportError:
        traceback.print_exc()

    # Comparison calculation
    if comparison:
        try:
            comp_raw, comp_time = time_calculation(comp, comp_pars, comp_n)
            comp_value = np.ma.masked_invalid(comp_raw)
            if verbose:
                print("%s t=%.2f ms, intensity=%.0f"
                      % (comp.engine, comp_time, comp_value.sum()))
            _show_invalid(data, comp_value)
        except ImportError:
            traceback.print_exc()

    # Compare, but only if computing both forms
    if comparison:
        resid = (base_value - comp_value)
        relerr = resid/np.where(comp_value != 0., abs(comp_value), 1.0)
        if verbose:
            _print_stats("|%s-%s|"
                         % (base.engine, comp.engine) + (" "*(3+len(comp.engine))),
                         resid)
            _print_stats("|(%s-%s)/%s|"
                         % (base.engine, comp.engine, comp.engine),
                         relerr)

    return dict(base_value=base_value, comp_value=comp_value,
                base_time=base_time, comp_time=comp_time,
                resid=resid, relerr=relerr)


def _print_stats(label, err):
    # type: (str, np.ma.ndarray) -> None
    # work with trimmed data, not the full set
    sorted_err = np.sort(abs(err.compressed()))
    if len(sorted_err) == 0.:
        print(label + "  no valid values")
        return

    p50 = int((len(sorted_err)-1)*0.50)
    p98 = int((len(sorted_err)-1)*0.98)
    data = [
        "max:%.3e"%sorted_err[-1],
        "median:%.3e"%sorted_err[p50],
        "98%%:%.3e"%sorted_err[p98],
        "rms:%.3e"%np.sqrt(np.mean(sorted_err**2)),
        "zero-offset:%+.3e"%np.mean(sorted_err),
        ]
    print(label+"  "+"  ".join(data))


def plot_models(opts, result, limits=(np.Inf, -np.Inf), setnum=0):
    # type: (Dict[str, Any], Dict[str, Any], Optional[Tuple[float, float]]) -> Tuple[float, float]
    base_value, comp_value = result['base_value'], result['comp_value']
    base_time, comp_time = result['base_time'], result['comp_time']
    resid, relerr = result['resid'], result['relerr']

    have_base, have_comp = (base_value is not None), (comp_value is not None)
    base, comp = opts['engines']
    data = opts['data']
    use_data = (opts['datafile'] is not None) and (have_base ^ have_comp)

    # Plot if requested
    view = opts['view']
    import matplotlib.pyplot as plt
    vmin, vmax = limits
    if have_base:
        vmin = min(vmin, base_value.min())
        vmax = max(vmax, base_value.max())
    if have_comp:
        vmin = min(vmin, comp_value.min())
        vmax = max(vmax, comp_value.max())
    limits = vmin, vmax

    if have_base:
        if have_comp:
            plt.subplot(131)
        plot_theory(data, base_value, view=view, use_data=use_data, limits=limits)
        plt.title("%s t=%.2f ms"%(base.engine, base_time))
        #cbar_title = "log I"
    if have_comp:
        if have_base:
            plt.subplot(132)
        if not opts['is2d'] and have_base:
            plot_theory(data, base_value, view=view, use_data=use_data, limits=limits)
        plot_theory(data, comp_value, view=view, use_data=use_data, limits=limits)
        plt.title("%s t=%.2f ms"%(comp.engine, comp_time))
        #cbar_title = "log I"
    if have_base and have_comp:
        plt.subplot(133)
        if not opts['rel_err']:
            err, errstr, errview = resid, "abs err", "linear"
        else:
            err, errstr, errview = abs(relerr), "rel err", "log"
        if 0:  # 95% cutoff
            sorted = np.sort(err.flatten())
            cutoff = sorted[int(sorted.size*0.95)]
            err[err > cutoff] = cutoff
        #err,errstr = base/comp,"ratio"
        plot_theory(data, None, resid=err, view=errview, use_data=use_data)
        if view == 'linear':
            plt.xscale('linear')
        plt.title("max %s = %.3g"%(errstr, abs(err).max()))
        #cbar_title = errstr if errview=="linear" else "log "+errstr
    #if is2D:
    #    h = plt.colorbar()
    #    h.ax.set_title(cbar_title)
    fig = plt.gcf()
    extra_title = ' '+opts['title'] if opts['title'] else ''
    fig.suptitle(":".join(opts['name']) + extra_title)

    if have_base and have_comp and opts['show_hist']:
        plt.figure()
        v = relerr
        v[v == 0] = 0.5*np.min(np.abs(v[v != 0]))
        plt.hist(np.log10(np.abs(v)), normed=1, bins=50)
        plt.xlabel('log10(err), err = |(%s - %s) / %s|'
                   % (base.engine, comp.engine, comp.engine))
        plt.ylabel('P(err)')
        plt.title('Distribution of relative error between calculation engines')

    return limits


# ===========================================================================
#

# Set of command line options.
# Normal options such as -plot/-noplot are specified as 'name'.
# For options such as -nq=500 which require a value use 'name='.
#
OPTIONS = [
    # Plotting
    'plot', 'noplot',
    'linear', 'log', 'q4',
    'rel', 'abs',
    'hist', 'nohist',
    'title=',

    # Data generation
    'data=', 'noise=', 'res=',
    'nq=', 'lowq', 'midq', 'highq', 'exq', 'zero',
    '2d', '1d',

    # Parameter set
    'preset', 'random', 'random=', 'sets=',
    'demo', 'default',  # TODO: remove demo/default
    'nopars', 'pars',

    # Calculation options
    'poly', 'mono', 'cutoff=',
    'magnetic', 'nonmagnetic',
    'accuracy=',
    'neval=',  # for timing...

    # Precision options
    'calc=',
    'half', 'fast', 'single', 'double', 'single!', 'double!', 'quad!',
    'sasview',  # TODO: remove sasview 3.x support

    # Output options
    'help', 'html', 'edit',
    ]

NAME_OPTIONS = set(k for k in OPTIONS if not k.endswith('='))
VALUE_OPTIONS = [k[:-1] for k in OPTIONS if k.endswith('=')]


def columnize(items, indent="", width=79):
    # type: (List[str], str, int) -> str
    """
    Format a list of strings into columns.

    Returns a string with carriage returns ready for printing.
    """
    column_width = max(len(w) for w in items) + 1
    num_columns = (width - len(indent)) // column_width
    num_rows = len(items) // num_columns
    items = items + [""] * (num_rows * num_columns - len(items))
    columns = [items[k*num_rows:(k+1)*num_rows] for k in range(num_columns)]
    lines = [" ".join("%-*s"%(column_width, entry) for entry in row)
             for row in zip(*columns)]
    output = indent + ("\n"+indent).join(lines)
    return output


def get_pars(model_info, use_demo=False):
    # type: (ModelInfo, bool) -> ParameterSet
    """
    Extract demo parameters from the model definition.
    """
    # Get the default values for the parameters
    pars = {}
    for p in model_info.parameters.call_parameters:
        parts = [('', p.default)]
        if p.polydisperse:
            parts.append(('_pd', 0.0))
            parts.append(('_pd_n', 0))
            parts.append(('_pd_nsigma', 3.0))
            parts.append(('_pd_type', "gaussian"))
        for ext, val in parts:
            if p.length > 1:
                dict(("%s%d%s" % (p.id, k, ext), val)
                     for k in range(1, p.length+1))
            else:
                pars[p.id + ext] = val

    # Plug in values given in demo
    if use_demo and model_info.demo:
        pars.update(model_info.demo)
    return pars

INTEGER_RE = re.compile("^[+-]?[1-9][0-9]*$")
def isnumber(str):
    match = FLOAT_RE.match(str)
    isfloat = (match and not str[match.end():])
    return isfloat or INTEGER_RE.match(str)

# For distinguishing pairs of models for comparison
# key-value pair separator =
# shell characters  | & ; <> $ % ' " \ # `
# model and parameter names _
# parameter expressions - + * / . ( )
# path characters including tilde expansion and windows drive ~ / :
# not sure about brackets [] {}
# maybe one of the following @ ? ^ ! ,
PAR_SPLIT = ','
def parse_opts(argv):
    # type: (List[str]) -> Dict[str, Any]
    """
    Parse command line options.
    """
    MODELS = core.list_models()
    flags = [arg for arg in argv
             if arg.startswith('-')]
    values = [arg for arg in argv
              if not arg.startswith('-') and '=' in arg]
    positional_args = [arg for arg in argv
                       if not arg.startswith('-') and '=' not in arg]
    models = "\n    ".join("%-15s"%v for v in MODELS)
    if len(positional_args) == 0:
        print(USAGE)
        print("\nAvailable models:")
        print(columnize(MODELS, indent="  "))
        return None

    invalid = [o[1:] for o in flags
               if o[1:] not in NAME_OPTIONS
               and not any(o.startswith('-%s='%t) for t in VALUE_OPTIONS)]
    if invalid:
        print("Invalid options: %s"%(", ".join(invalid)))
        return None

    name = positional_args[-1]

    # pylint: disable=bad-whitespace
    # Interpret the flags
    opts = {
        'plot'      : True,
        'view'      : 'log',
        'is2d'      : False,
        'qmax'      : 0.05,
        'nq'        : 128,
        'res'       : 0.0,
        'noise'     : 0.0,
        'accuracy'  : 'Low',
        'cutoff'    : '0.0',
        'seed'      : -1,  # default to preset
        'mono'      : True,
        # Default to magnetic a magnetic moment is set on the command line
        'magnetic'  : False,
        'show_pars' : False,
        'show_hist' : False,
        'rel_err'   : True,
        'explore'   : False,
        'use_demo'  : True,
        'zero'      : False,
        'html'      : False,
        'title'     : None,
        'datafile'  : None,
        'sets'      : 0,
        'engine'    : 'default',
        'evals'     : '1',
    }
    for arg in flags:
        if arg == '-noplot':    opts['plot'] = False
        elif arg == '-plot':    opts['plot'] = True
        elif arg == '-linear':  opts['view'] = 'linear'
        elif arg == '-log':     opts['view'] = 'log'
        elif arg == '-q4':      opts['view'] = 'q4'
        elif arg == '-1d':      opts['is2d'] = False
        elif arg == '-2d':      opts['is2d'] = True
        elif arg == '-exq':     opts['qmax'] = 10.0
        elif arg == '-highq':   opts['qmax'] = 1.0
        elif arg == '-midq':    opts['qmax'] = 0.2
        elif arg == '-lowq':    opts['qmax'] = 0.05
        elif arg == '-zero':    opts['zero'] = True
        elif arg.startswith('-nq='):       opts['nq'] = int(arg[4:])
        elif arg.startswith('-res='):      opts['res'] = float(arg[5:])
        elif arg.startswith('-noise='):    opts['noise'] = float(arg[7:])
        elif arg.startswith('-sets='):     opts['sets'] = int(arg[6:])
        elif arg.startswith('-accuracy='): opts['accuracy'] = arg[10:]
        elif arg.startswith('-cutoff='):   opts['cutoff'] = arg[8:]
        elif arg.startswith('-random='):   opts['seed'] = int(arg[8:])
        elif arg.startswith('-title='):    opts['title'] = arg[7:]
        elif arg.startswith('-data='):     opts['datafile'] = arg[6:]
        elif arg.startswith('-calc='):     opts['engine'] = arg[6:]
        elif arg.startswith('-neval='):    opts['evals'] = arg[7:]
        elif arg == '-random':  opts['seed'] = np.random.randint(1000000)
        elif arg == '-preset':  opts['seed'] = -1
        elif arg == '-mono':    opts['mono'] = True
        elif arg == '-poly':    opts['mono'] = False
        elif arg == '-magnetic':       opts['magnetic'] = True
        elif arg == '-nonmagnetic':    opts['magnetic'] = False
        elif arg == '-pars':    opts['show_pars'] = True
        elif arg == '-nopars':  opts['show_pars'] = False
        elif arg == '-hist':    opts['show_hist'] = True
        elif arg == '-nohist':  opts['show_hist'] = False
        elif arg == '-rel':     opts['rel_err'] = True
        elif arg == '-abs':     opts['rel_err'] = False
        elif arg == '-half':    opts['engine'] = 'half'
        elif arg == '-fast':    opts['engine'] = 'fast'
        elif arg == '-single':  opts['engine'] = 'single'
        elif arg == '-double':  opts['engine'] = 'double'
        elif arg == '-single!': opts['engine'] = 'single!'
        elif arg == '-double!': opts['engine'] = 'double!'
        elif arg == '-quad!':   opts['engine'] = 'quad!'
        elif arg == '-sasview': opts['engine'] = 'sasview'
        elif arg == '-edit':    opts['explore'] = True
        elif arg == '-demo':    opts['use_demo'] = True
        elif arg == '-default': opts['use_demo'] = False
        elif arg == '-html':    opts['html'] = True
        elif arg == '-help':    opts['html'] = True
    # pylint: enable=bad-whitespace

    # Magnetism forces 2D for now
    if opts['magnetic']:
        opts['is2d'] = True

    # Force random if sets is used
    if opts['sets'] >= 1 and opts['seed'] < 0:
        opts['seed'] = np.random.randint(1000000)
    if opts['sets'] == 0:
        opts['sets'] = 1

    # Create the computational engines
    if opts['datafile'] is not None:
        data = load_data(os.path.expanduser(opts['datafile']))
    else:
        data, _ = make_data(opts)

    comparison = any(PAR_SPLIT in v for v in values)
    if PAR_SPLIT in name:
        names = name.split(PAR_SPLIT, 2)
        comparison = True
    else:
        names = [name]*2
    try:
        model_info = [core.load_model_info(k) for k in names]
    except ImportError as exc:
        print(str(exc))
        print("Could not find model; use one of:\n    " + models)
        return None

    if PAR_SPLIT in opts['engine']:
        engine_types = opts['engine'].split(PAR_SPLIT, 2)
        comparison = True
    else:
        engine_types = [opts['engine']]*2

    if PAR_SPLIT in opts['evals']:
        evals = [int(k) for k in opts['evals'].split(PAR_SPLIT, 2)]
        comparison = True
    else:
        evals = [int(opts['evals'])]*2

    if PAR_SPLIT in opts['cutoff']:
        cutoff = [float(k) for k in opts['cutoff'].split(PAR_SPLIT, 2)]
        comparison = True
    else:
        cutoff = [float(opts['cutoff'])]*2

    base = make_engine(model_info[0], data, engine_types[0], cutoff[0])
    if comparison:
        comp = make_engine(model_info[1], data, engine_types[1], cutoff[1])
    else:
        comp = None

    # pylint: disable=bad-whitespace
    # Remember it all
    opts.update({
        'data'      : data,
        'name'      : names,
        'def'       : model_info,
        'count'     : evals,
        'engines'   : [base, comp],
        'values'    : values,
    })
    # pylint: enable=bad-whitespace

    return opts

def parse_pars(opts):
    model_info, model_info2 = opts['def']

    # Get demo parameters from model definition, or use default parameters
    # if model does not define demo parameters
    pars = get_pars(model_info, opts['use_demo'])
    pars2 = get_pars(model_info2, opts['use_demo'])
    pars2.update((k, v) for k, v in pars.items() if k in pars2)
    # randomize parameters
    #pars.update(set_pars)  # set value before random to control range
    if opts['seed'] > -1:
        pars = randomize_pars(model_info, pars)
        if model_info != model_info2:
            pars2 = randomize_pars(model_info2, pars2)
            # Share values for parameters with the same name
            for k, v in pars.items():
                if k in pars2:
                    pars2[k] = v
        else:
            pars2 = pars.copy()
        constrain_pars(model_info, pars)
        constrain_pars(model_info2, pars2)
    pars = suppress_pd(pars, opts['mono'])
    pars2 = suppress_pd(pars2, opts['mono'])
    pars = suppress_magnetism(pars, not opts['magnetic'])
    pars2 = suppress_magnetism(pars2, not opts['magnetic'])

    # Fill in parameters given on the command line
    presets = {}
    presets2 = {}
    for arg in opts['values']:
        k, v = arg.split('=', 1)
        if k not in pars and k not in pars2:
            # extract base name without polydispersity info
            s = set(p.split('_pd')[0] for p in pars)
            print("%r invalid; parameters are: %s"%(k, ", ".join(sorted(s))))
            return None
        v1, v2 = v.split(PAR_SPLIT, 2) if PAR_SPLIT in v else (v,v)
        if v1 and k in pars:
            presets[k] = float(v1) if isnumber(v1) else v1
        if v2 and k in pars2:
            presets2[k] = float(v2) if isnumber(v2) else v2

    # If pd given on the command line, default pd_n to 35
    for k, v in list(presets.items()):
        if k.endswith('_pd'):
            presets.setdefault(k+'_n', 35.)
    for k, v in list(presets2.items()):
        if k.endswith('_pd'):
            presets2.setdefault(k+'_n', 35.)

    # Evaluate preset parameter expressions
    context = MATH.copy()
    context['np'] = np
    context.update(pars)
    context.update((k, v) for k, v in presets.items() if isinstance(v, float))
    for k, v in presets.items():
        if not isinstance(v, float) and not k.endswith('_type'):
            presets[k] = eval(v, context)
    context.update(presets)
    context.update((k, v) for k, v in presets2.items() if isinstance(v, float))
    for k, v in presets2.items():
        if not isinstance(v, float) and not k.endswith('_type'):
            presets2[k] = eval(v, context)

    # update parameters with presets
    pars.update(presets)  # set value after random to control value
    pars2.update(presets2)  # set value after random to control value
    #import pprint; pprint.pprint(model_info)

    if opts['show_pars']:
        if model_info.name != model_info2.name or pars != pars2:
            print("==== %s ====="%model_info.name)
            print(str(parlist(model_info, pars, opts['is2d'])))
            print("==== %s ====="%model_info2.name)
            print(str(parlist(model_info2, pars2, opts['is2d'])))
        else:
            print(str(parlist(model_info, pars, opts['is2d'])))

    return pars, pars2

def show_docs(opts):
    # type: (Dict[str, Any]) -> None
    """
    show html docs for the model
    """
    import os
    from .generate import make_html
    from . import rst2html

    info = opts['def'][0]
    html = make_html(info)
    path = os.path.dirname(info.filename)
    url = "file://"+path.replace("\\","/")[2:]+"/"
    rst2html.view_html_qtapp(html, url)

def explore(opts):
    # type: (Dict[str, Any]) -> None
    """
    explore the model using the bumps gui.
    """
    import wx  # type: ignore
    from bumps.names import FitProblem  # type: ignore
    from bumps.gui.app_frame import AppFrame  # type: ignore
    from bumps.gui import signal

    is_mac = "cocoa" in wx.version()
    # Create an app if not running embedded
    app = wx.App() if wx.GetApp() is None else None
    model = Explore(opts)
    problem = FitProblem(model)
    frame = AppFrame(parent=None, title="explore", size=(1000, 700))
    if not is_mac:
        frame.Show()
    frame.panel.set_model(model=problem)
    frame.panel.Layout()
    frame.panel.aui.Split(0, wx.TOP)
    def reset_parameters(event):
        model.revert_values()
        signal.update_parameters(problem)
    frame.Bind(wx.EVT_TOOL, reset_parameters, frame.ToolBar.GetToolByPos(1))
    if is_mac: frame.Show()
    # If running withing an app, start the main loop
    if app:
        app.MainLoop()

class Explore(object):
    """
    Bumps wrapper for a SAS model comparison.

    The resulting object can be used as a Bumps fit problem so that
    parameters can be adjusted in the GUI, with plots updated on the fly.
    """
    def __init__(self, opts):
        # type: (Dict[str, Any]) -> None
        from bumps.cli import config_matplotlib  # type: ignore
        from . import bumps_model
        config_matplotlib()
        self.opts = opts
        opts['pars'] = list(opts['pars'])
        p1, p2 = opts['pars']
        m1, m2 = opts['def']
        self.fix_p2 = m1 != m2 or p1 != p2
        model_info = m1
        pars, pd_types = bumps_model.create_parameters(model_info, **p1)
        # Initialize parameter ranges, fixing the 2D parameters for 1D data.
        if not opts['is2d']:
            for p in model_info.parameters.user_parameters({}, is2d=False):
                for ext in ['', '_pd', '_pd_n', '_pd_nsigma']:
                    k = p.name+ext
                    v = pars.get(k, None)
                    if v is not None:
                        v.range(*parameter_range(k, v.value))
        else:
            for k, v in pars.items():
                v.range(*parameter_range(k, v.value))

        self.pars = pars
        self.starting_values = dict((k, v.value) for k, v in pars.items())
        self.pd_types = pd_types
        self.limits = np.Inf, -np.Inf

    def revert_values(self):
        for k, v in self.starting_values.items():
            self.pars[k].value = v

    def model_update(self):
        pass

    def numpoints(self):
        # type: () -> int
        """
        Return the number of points.
        """
        return len(self.pars) + 1  # so dof is 1

    def parameters(self):
        # type: () -> Any   # Dict/List hierarchy of parameters
        """
        Return a dictionary of parameters.
        """
        return self.pars

    def nllf(self):
        # type: () -> float
        """
        Return cost.
        """
        # pylint: disable=no-self-use
        return 0.  # No nllf

    def plot(self, view='log'):
        # type: (str) -> None
        """
        Plot the data and residuals.
        """
        pars = dict((k, v.value) for k, v in self.pars.items())
        pars.update(self.pd_types)
        self.opts['pars'][0] = pars
        if not self.fix_p2:
            self.opts['pars'][1] = pars
        result = run_models(self.opts)
        limits = plot_models(self.opts, result, limits=self.limits)
        if self.limits is None:
            vmin, vmax = limits
            self.limits = vmax*1e-7, 1.3*vmax
            import pylab; pylab.clf()
            plot_models(self.opts, result, limits=self.limits)


def main(*argv):
    # type: (*str) -> None
    """
    Main program.
    """
    opts = parse_opts(argv)
    if opts is not None:
        if opts['seed'] > -1:
            print("Randomize using -random=%i"%opts['seed'])
            np.random.seed(opts['seed'])
        if opts['html']:
            show_docs(opts)
        elif opts['explore']:
            opts['pars'] = parse_pars(opts)
            if opts['pars'] is None:
                return
            explore(opts)
        else:
            compare(opts)

if __name__ == "__main__":
    main(*sys.argv[1:])

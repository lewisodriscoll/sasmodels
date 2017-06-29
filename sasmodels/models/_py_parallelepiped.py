# parallelepiped model
# Note: model title and parameter table are inserted automatically
r"""
The form factor is normalized by the particle volume.
For information about polarised and magnetic scattering, see
the :ref:`magnetism` documentation.

Definition
----------

 This model calculates the scattering from a rectangular parallelepiped
 (\:numref:`parallelepiped-image`\).
 If you need to apply polydispersity, see also :ref:`rectangular-prism`.

.. _parallelepiped-image:


.. figure:: img/parallelepiped_geometry.jpg

   Parallelepiped with the corresponding definition of sides.

.. note::

   The edge of the solid used to have to satisfy the condition that $A < B < C$.
   After some improvements to the effective radius calculation, used with
   an S(Q), it is beleived that this is no longer the case.

The 1D scattering intensity $I(q)$ is calculated as:

.. Comment by Miguel Gonzalez:
   I am modifying the original text because I find the notation a little bit
   confusing. I think that in most textbooks/papers, the notation P(Q) is
   used for the form factor (adim, P(Q=0)=1), although F(q) seems also to
   be used. But here (as for many other models), P(q) is used to represent
   the scattering intensity (in cm-1 normally). It would be good to agree on
   a common notation.

.. math::

    I(q) = \frac{\text{scale}}{V} (\Delta\rho \cdot V)^2
           \left< P(q, \alpha) \right> + \text{background}

where the volume $V = A B C$, the contrast is defined as
$\Delta\rho = \rho_\text{p} - \rho_\text{solvent}$,
$P(q, \alpha)$ is the form factor corresponding to a parallelepiped oriented
at an angle $\alpha$ (angle between the long axis C and $\vec q$),
and the averaging $\left<\ldots\right>$ is applied over all orientations.

Assuming $a = A/B < 1$, $b = B /B = 1$, and $c = C/B > 1$, the
form factor is given by (Mittelbach and Porod, 1961)

.. math::

    P(q, \alpha) = \int_0^1 \phi_Q\left(\mu \sqrt{1-\sigma^2},a\right)
        \left[S(\mu c \sigma/2)\right]^2 d\sigma

with

.. math::

    \phi_Q(\mu,a) &= \int_0^1
        \left\{S\left[\frac{\mu}{2}\cos\left(\frac{\pi}{2}u\right)\right]
               S\left[\frac{\mu a}{2}\sin\left(\frac{\pi}{2}u\right)\right]
               \right\}^2 du

    S(x) &= \frac{\sin x}{x}

    \mu &= qB

The scattering intensity per unit volume is returned in units of |cm^-1|.

NB: The 2nd virial coefficient of the parallelepiped is calculated based on
the averaged effective radius, after appropriately sorting the three
dimensions, to give an oblate or prolate particle, $(=\sqrt{AB/\pi})$ and
length $(= C)$ values, and used as the effective radius for
$S(q)$ when $P(q) \cdot S(q)$ is applied.

To provide easy access to the orientation of the parallelepiped, we define
three angles $\theta$, $\phi$ and $\Psi$. The definition of $\theta$ and
$\phi$ is the same as for the cylinder model (see also figures below).

.. Comment by Miguel Gonzalez:
   The following text has been commented because I think there are two
   mistakes. Psi is the rotational angle around C (but I cannot understand
   what it means against the q plane) and psi=0 corresponds to a||x and b||y.

   The angle $\Psi$ is the rotational angle around the $C$ axis against
   the $q$ plane. For example, $\Psi = 0$ when the $B$ axis is parallel
   to the $x$-axis of the detector.

The angle $\Psi$ is the rotational angle around the $C$ axis.
For $\theta = 0$ and $\phi = 0$, $\Psi = 0$ corresponds to the $B$ axis
oriented parallel to the y-axis of the detector with $A$ along the z-axis.
For other $\theta$, $\phi$ values, the parallelepiped has to be first rotated
$\theta$ degrees around $z$ and $\phi$ degrees around $y$,
before doing a final rotation of $\Psi$ degrees around the resulting $C$ to
obtain the final orientation of the parallelepiped.
For example, for $\theta = 0$ and $\phi = 90$, we have that $\Psi = 0$
corresponds to $A$ along $x$ and $B$ along $y$,
while for $\theta = 90$ and $\phi = 0$, $\Psi = 0$ corresponds to
$A$ along $z$ and $B$ along $x$.

.. _parallelepiped-orientation:

.. figure:: img/parallelepiped_angle_definition.png

    Definition of the angles for oriented parallelepiped, shown with $A<B<C$.

.. figure:: img/parallelepiped_angle_projection.png

    Examples of the angles for an oriented parallelepiped against the
    detector plane.

On introducing "Orientational Distribution" in the angles, "distribution of theta" and "distribution of phi" parameters will
appear. These are actually rotations about axes $\delta_1$ and $\delta_2$ of the parallelepiped, perpendicular to the $a$ x $c$ and $b$ x $c$ faces. 
(When $\theta = \phi = 0$ these are parallel to the $Y$ and $X$ axes of the instrument.) The third orientation distribution, in $\psi$, is 
about the $c$ axis of the particle, perpendicular to the $a$ x $b$ face. Some experimentation may be required to 
understand the 2d patterns fully. (Earlier implementations had numerical integration issues in some circumstances when orientation 
distributions passed through 90 degrees, such situations, with very broad distributions, should still be approached with care.) 

    
For a given orientation of the parallelepiped, the 2D form factor is
calculated as

.. math::

    P(q_x, q_y) = \left[\frac{\sin(\tfrac{1}{2}qA\cos\alpha)}{(\tfrac{1}{2}qA\cos\alpha)}\right]^2
                  \left[\frac{\sin(\tfrac{1}{2}qB\cos\beta)}{(\tfrac{1}{2}qB\cos\beta)}\right]^2
                  \left[\frac{\sin(\tfrac{1}{2}qC\cos\gamma)}{(\tfrac{1}{2}qC\cos\gamma)}\right]^2

with

.. math::

    \cos\alpha &= \hat A \cdot \hat q,

    \cos\beta  &= \hat B \cdot \hat q,

    \cos\gamma &= \hat C \cdot \hat q

and the scattering intensity as:

.. math::

    I(q_x, q_y) = \frac{\text{scale}}{V} V^2 \Delta\rho^2 P(q_x, q_y)
            + \text{background}

.. Comment by Miguel Gonzalez:
   This reflects the logic of the code, as in parallelepiped.c the call
   to _pkernel returns $P(q_x, q_y)$ and then this is multiplied by
   $V^2 * (\Delta \rho)^2$. And finally outside parallelepiped.c it will be
   multiplied by scale, normalized by $V$ and the background added. But
   mathematically it makes more sense to write
   $I(q_x, q_y) = \text{scale} V \Delta\rho^2 P(q_x, q_y) + \text{background}$,
   with scale being the volume fraction.


Validation
----------

Validation of the code was done by comparing the output of the 1D calculation
to the angular average of the output of a 2D calculation over all possible
angles.


References
----------

P Mittelbach and G Porod, *Acta Physica Austriaca*, 14 (1961) 185-211

R Nayuk and K Huber, *Z. Phys. Chem.*, 226 (2012) 837-854

Authorship and Verification
----------------------------

* **Author:** This model is based on form factor calculations implemented
    in a c-library provided by the NIST Center for Neutron Research (Kline, 2006).
* **Last Modified by:**  Paul Kienzle **Date:** April 05, 2017
* **Last Reviewed by:**  Richard Heenan **Date:** April 06, 2017

"""

import numpy as np
from numpy import pi, inf, sqrt, sin, cos, radians
from sasmodels.special import sas_sinx_x, Gauss76Wt, Gauss76Z, square, ORIENT_ASYMMETRIC

name = "parallelepiped"
title = "Rectangular parallelepiped with uniform scattering length density."
description = """
    I(q)= scale*V*(sld - sld_solvent)^2*P(q,alpha)+background
        P(q,alpha) = integral from 0 to 1 of ...
           phi(mu*sqrt(1-sigma^2),a) * S(mu*c*sigma/2)^2 * dsigma
        with
            phi(mu,a) = integral from 0 to 1 of ..
            (S((/mu/2)*cos(pi*u/2))*S((mu*a/2)*sin(pi*u/2)))^2 * du
            S(x) = sin(x)/x
            mu = q*B
        V: Volume of the rectangular parallelepiped
        alpha: angle between the long axis of the
            parallelepiped and the q-vector for 1D
"""
category = "shape:parallelepiped"

#             ["name", "units", default, [lower, upper], "type","description"],
parameters = [["sld", "1e-6/Ang^2", 4, [-inf, inf], "sld",
               "Parallelepiped scattering length density"],
              ["sld_solvent", "1e-6/Ang^2", 1, [-inf, inf], "sld",
               "Solvent scattering length density"],
              ["length_a", "Ang", 35, [0, inf], "volume",
               "Shorter side of the parallelepiped"],
              ["length_b", "Ang", 75, [0, inf], "volume",
               "Second side of the parallelepiped"],
              ["length_c", "Ang", 400, [0, inf], "volume",
               "Larger side of the parallelepiped"],
              ["theta", "degrees", 60, [-360, 360], "orientation",
               "c axis to beam angle"],
              ["phi", "degrees", 60, [-360, 360], "orientation",
               "rotation about beam"],
              ["psi", "degrees", 60, [-360, 360], "orientation",
               "rotation about c axis"],
             ]

def form_volume(length_a, length_b, length_c):
    return length_a * length_b * length_c
             
def Iq(q,
        sld, solvent_sld,
        length_a, length_b, length_c):

    mu = 0.5 * q * length_b
    
    # Scale sides by B
    a_scaled = length_a / length_b
    c_scaled = length_c / length_b
        
    # outer integral (with gauss points), integration limits = 0, 1
    outer_total = 0 #initialize integral

    for i in range(76):
        sigma = 0.5 * ( Gauss76Z[i] + 1.0 );
        mu_proj = mu * sqrt(1.0-sigma*sigma)

        # inner integral (with gauss points), integration limits = 0, 1
        # corresponding to angles from 0 to pi/2.
        inner_total = 0.0
        for j in range(76):
            uu = 0.5 * ( Gauss76Z[j] + 1.0 );
            sin_uu, cos_uu = sin(0.5*pi*uu), cos(0.5*pi*uu)
            si1 = sas_sinx_x(mu_proj * sin_uu * a_scaled)
            si2 = sas_sinx_x(mu_proj * cos_uu)
            inner_total += Gauss76Wt[j] * square(si1 * si2)
        inner_total *= 0.5

        si = sas_sinx_x(mu * c_scaled * sigma)
        outer_total += Gauss76Wt[i] * inner_total * si * si
    outer_total *= 0.5

    # Multiply by contrast^2 and convert from [1e-12 A-1] to [cm-1]
    V = form_volume(length_a, length_b, length_c)
    drho = (sld-solvent_sld)
    return 1.0e-4 * square(drho * V) * outer_total
Iq.vectorized = True

def Iqxy(qx, qy,
        sld, solvent_sld,
        length_a, length_b, length_c,
        theta, phi, psi):
    q, xhat, yhat, zhat = ORIENT_ASYMMETRIC(qx, qy, theta, phi, psi)
    siA = sas_sinx_x(0.5*length_a*q*xhat)
    siB = sas_sinx_x(0.5*length_b*q*yhat)
    siC = sas_sinx_x(0.5*length_c*q*zhat)
    V = form_volume(length_a, length_b, length_c)
    drho = (sld - solvent_sld)
    form = V * drho * siA * siB * siC
    # Square and convert from [1e-12 A-1] to [cm-1]
    return 1.0e-4 * form * form
Iqxy.vectorized = True


def ER(length_a, length_b, length_c):
    """
    Return effective radius (ER) for P(q)*S(q)
    """
    # now that axes can be in any size order, need to sort a,b,c where a~b and c is either much smaller
    # or much larger
    abc = np.vstack((length_a, length_b, length_c))
    abc = np.sort(abc, axis=0)
    selector = (abc[1] - abc[0]) > (abc[2] - abc[1])
    length = np.where(selector, abc[0], abc[2])
    # surface average radius (rough approximation)
    radius = np.sqrt(np.where(~selector, abc[0]*abc[1], abc[1]*abc[2]) / pi)

    ddd = 0.75 * radius * (2*radius*length + (length + radius)*(length + pi*radius))
    return 0.5 * (ddd) ** (1. / 3.)

# VR defaults to 1.0

# parameters for demo
demo = dict(scale=1, background=0,
            sld=6.3, sld_solvent=1.0,
            length_a=35, length_b=75, length_c=400,
            theta=45, phi=30, psi=15,
            length_a_pd=0.1, length_a_pd_n=10,
            length_b_pd=0.1, length_b_pd_n=1,
            length_c_pd=0.1, length_c_pd_n=1,
            theta_pd=10, theta_pd_n=1,
            phi_pd=10, phi_pd_n=1,
            psi_pd=10, psi_pd_n=10)
# rkh 7/4/17 add random unit test for 2d, note make all params different, 2d values not tested against other codes or models
qx, qy = 0.2 * cos(pi/6.), 0.2 * sin(pi/6.)
tests = [[{}, 0.2, 0.17758004974],
         [{}, [0.2], [0.17758004974]],
         [{'theta':10.0, 'phi':20.0}, (qx, qy), 0.0089517140475],
         [{'theta':10.0, 'phi':20.0}, [(qx, qy)], [0.0089517140475]],
        ]
del qx, qy  # not necessary to delete, but cleaner
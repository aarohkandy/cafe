# ruff: noqa
"""Hull terms vendored from Thor I. Fossen's PythonVehicleSimulator (MIT licence, see LICENSE in this directory).

Source: https://github.com/cybergalactic/PythonVehicleSimulator, commit a93d1938ba1f78f2580c24c73f003091b2f03cd0 (HEAD on 2026-10-29)
  src/python_vehicle_simulator/lib/gnc.py          sha256 2f5c5a8330d411f3ee863eb635faa40f794fd4dc274fe3b0a7a9c3526eb4a476
  src/python_vehicle_simulator/vehicles/remus100.py sha256 54e872b819a5609614ec31584347e4a304c271f3271abc87b7b4f32dd34b2943
  src/python_vehicle_simulator/vehicles/otter.py    sha256 4823db16441c3e90bf3dc15c0ea7bd2b55d5663c32f17fac7e7dbc608b0b64d9
Only what the comparison needs: Smtrx, Hmtrx and m2c are copied verbatim from gnc.py; remus100_mass / otter_mass are the
mass-matrix lines of the two __init__ methods; remus100_C / otter_C are the Coriolis lines of their dynamics() methods.
Nothing here is cafe code. Propulsion, damping, lift/drag, restoring forces and actuators are NOT vendored.
"""
import math

import numpy as np

def Smtrx(a):
    """
    S = Smtrx(a) computes the 3x3 vector skew-symmetric matrix S(a) = -S(a)'.
    The cross product satisfies: a x b = S(a)b. 
    """
 
    S = np.array([ 
        [ 0, -a[2], a[1] ],
        [ a[2],   0,     -a[0] ],
        [-a[1],   a[0],   0 ]  ])

    return S


def Hmtrx(r):
    """
    H = Hmtrx(r) computes the 6x6 system transformation matrix
    H = [eye(3)     S'
         zeros(3,3) eye(3) ]       Property: inv(H(r)) = H(-r)

    If r = r_bg is the vector from the CO to the CG, the model matrices in CO and
    CG are related by: M_CO = H(r_bg)' * M_CG * H(r_bg). Generalized position and
    force satisfy: eta_CO = H(r_bg)' * eta_CG and tau_CO = H(r_bg)' * tau_CG 
    """

    H = np.identity(6,float)
    H[0:3, 3:6] = Smtrx(r).T

    return H


def m2c(M, nu):
    """
    C = m2c(M,nu) computes the Coriolis and centripetal matrix C from the
    mass matrix M and generalized velocity vector nu (Fossen 2021, Ch. 3)
    """

    M = 0.5 * (M + M.T)     # systematization of the inertia matrix

    if (len(nu) == 6):      #  6-DOF model
    
        M11 = M[0:3,0:3]
        M12 = M[0:3,3:6] 
        M21 = M12.T
        M22 = M[3:6,3:6] 
    
        nu1 = nu[0:3]
        nu2 = nu[3:6]
        dt_dnu1 = np.matmul(M11,nu1) + np.matmul(M12,nu2)
        dt_dnu2 = np.matmul(M21,nu1) + np.matmul(M22,nu2)

        #C  = [  zeros(3,3)      -Smtrx(dt_dnu1)
        #      -Smtrx(dt_dnu1)  -Smtrx(dt_dnu2) ]
        C = np.zeros( (6,6) )    
        C[0:3,3:6] = -Smtrx(dt_dnu1)
        C[3:6,0:3] = -Smtrx(dt_dnu1)
        C[3:6,3:6] = -Smtrx(dt_dnu2)
            
    else:   # 3-DOF model (surge, sway and yaw)
        #C = [ 0             0            -M(2,2)*nu(2)-M(2,3)*nu(3)
        #      0             0             M(1,1)*nu(1)
        #      M(2,2)*nu(2)+M(2,3)*nu(3)  -M(1,1)*nu(1)          0  ]    
        C = np.zeros( (3,3) ) 
        C[0,2] = -M[1,1] * nu[1] - M[1,2] * nu[2]
        C[1,2] =  M[0,0] * nu[0] 
        C[2,0] = -C[0,2]       
        C[2,1] = -C[1,2]
        
    return C


def remus100_mass():
    """remus100.__init__ lines 'Hydrodynamics' to 'Mass matrix including added mass'. -> dict(m, Ix, Iy, r_bg, MRB, MA, M) in CO."""
    L, diam, rho = 1.6, 0.19, 1026
    a, b = L / 2, diam / 2
    r_bg = np.array([0, 0, 0.02], float)
    m = 4 / 3 * math.pi * rho * a * b ** 2
    Ix = (2 / 5) * m * b ** 2
    Iy = (1 / 5) * m * (a ** 2 + b ** 2)
    MRB_CG = np.diag([m, m, m, Ix, Iy, Iy])
    H_rg = Hmtrx(r_bg)
    MRB = H_rg.T @ MRB_CG @ H_rg
    MA_44 = 0.3 * Ix
    e = math.sqrt(1 - (b / a) ** 2)
    alpha_0 = (2 * (1 - e ** 2) / pow(e, 3)) * (0.5 * math.log((1 + e) / (1 - e)) - e)
    beta_0 = 1 / (e ** 2) - (1 - e ** 2) / (2 * pow(e, 3)) * math.log((1 + e) / (1 - e))
    k1 = alpha_0 / (2 - alpha_0)
    k2 = beta_0 / (2 - beta_0)
    k_prime = pow(e, 4) * (beta_0 - alpha_0) / ((2 - e ** 2) * (2 * e ** 2 - (2 - e ** 2) * (beta_0 - alpha_0)))
    MA = np.diag([m * k1, m * k2, m * k2, MA_44, k_prime * Iy, k_prime * Iy])
    return dict(m=m, Ix=Ix, Iy=Iy, r_bg=r_bg, MRB=MRB, MA=MA, M=MRB + MA, L=L, diam=diam, rho=rho)


def remus100_C(MRB, MA, nu_r, stabilised=True):
    """remus100.dynamics: C = m2c(MRB, nu_r) + m2c(MA, nu_r), with (stabilised=True, as shipped) the eight added-mass
    Coriolis entries 'quadratic velocity terms due to pitching' and 'Munk moment in yaw' set to zero."""
    CRB = m2c(MRB, nu_r)
    CA = m2c(MA, nu_r)
    if stabilised:
        CA[4][0] = 0
        CA[0][4] = 0
        CA[4][2] = 0
        CA[2][4] = 0
        CA[5][0] = 0
        CA[0][5] = 0
        CA[5][1] = 0
        CA[1][5] = 0
    return CRB + CA


def otter_mass():
    """otter.__init__ lines from 'Vehicle parameters' to 'System mass matrix'. -> dict(m_total, Ig, r_g, MRB, MA, M) in CO."""
    m, mp = 55.0, 25.0
    rp = np.array([0.05, 0, -0.35], float)
    rg = np.array([0.2, 0, -0.2], float)
    rg = (m * rg + mp * rp) / (m + mp)
    S_rg, S_rp = Smtrx(rg), Smtrx(rp)
    H_rg = Hmtrx(rg)
    B, L = 1.08, 2.0
    R44, R55, R66 = 0.4 * B, 0.25 * L, 0.25 * L
    Ig_CG = m * np.diag(np.array([R44 ** 2, R55 ** 2, R66 ** 2]))
    Ig = Ig_CG - m * S_rg @ S_rg - mp * S_rp @ S_rp
    MRB_CG = np.zeros((6, 6))
    MRB_CG[0:3, 0:3] = (m + mp) * np.identity(3)
    MRB_CG[3:6, 3:6] = Ig
    MRB = H_rg.T @ MRB_CG @ H_rg
    MA = -np.diag([-0.1 * m, -1.5 * m, -1.0 * m, -0.2 * Ig[0, 0], -0.8 * Ig[1, 1], -1.7 * Ig[2, 2]])
    return dict(m_total=m + mp, Ig=Ig, r_g=rg, MRB=MRB, MA=MA, M=MRB + MA, H_rg=H_rg)


def otter_C(o, nu, nu_r):
    """otter.dynamics: CRB_CG from the body rates, moved to CO with H_rg, plus CA = m2c(MA, nu_r)."""
    CRB_CG = np.zeros((6, 6))
    CRB_CG[0:3, 0:3] = o["m_total"] * Smtrx(nu[3:6])
    CRB_CG[3:6, 3:6] = -Smtrx(np.matmul(o["Ig"], nu[3:6]))
    CRB = o["H_rg"].T @ CRB_CG @ o["H_rg"]
    return CRB + m2c(o["MA"], nu_r)

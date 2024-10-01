# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/03_models.ipynb.

# %% auto 0
__all__ = ['adjoint', 'initialize_weights_to_zero', 'ToyODE', 'make_model', 'Autoencoder', 'ToyModel', 'ToySDEModel',
           'GrowthRateModel', 'GrowthRateSDEModel']

# %% ../nbs/03_models.ipynb 3
import itertools
from torch.nn  import functional as F 
import torch.nn as nn
import torch

# Initialize the weights and biases to zero
def initialize_weights_to_zero(module):
    if isinstance(module, nn.Linear):
        nn.init.constant_(module.weight, 0)  # Set weights to 0
        if module.bias is not None:
            nn.init.constant_(module.bias, 0)  # Set biases to 0

class ToyODE(nn.Module):
    """ 
    ODE derivative network
    
    feature_dims (int) default '5': dimension of the inputs, either in ambient space or embedded space.
    layer (list of int) defaulf ''[64]'': the hidden layers of the network.
    activation (torch.nn) default '"ReLU"': activation function applied in between layers.
    scales (NoneType|list of float) default 'None': the initial scale for the noise in the trajectories. One scale per bin, add more if using an adaptative ODE solver.
    n_aug (int) default '1': number of added dimensions to the input of the network. Total dimensions are features_dim + 1 (time) + n_aug. 
    
    Method
    forward (Callable)
        forward pass of the ODE derivative network.
        Parameters:
        t (torch.tensor): time of the evaluation.
        x (torch.tensor): position of the evalutation.
        Return:
        derivative at time t and position x.   
    """
    def __init__(
        self, 
        feature_dims=5,
        layers=[64],
        activation='ReLU',
        scales=None,
        n_aug=2,
        zero_gate=False,
        time_homogeneous=False,
        unif_velo=False,
        unif_velo_strict=False,
        unif_velo_t=False,
        separate_network_m=False,
        m_zero_weight_init=True,
    ):
        super(ToyODE, self).__init__()
        self.time_homogeneous = time_homogeneous
        t_dim = 0 if time_homogeneous else 1
        self.separate_network_m = separate_network_m

        if separate_network_m: # x does not depend on m, but m does depend on x.
            x_feature_dims = feature_dims - 1 # remove the m dim for x seq
            steps = [x_feature_dims+t_dim+n_aug, *layers, x_feature_dims]
            pairs = zip(steps, steps[1:])
            chain = list(itertools.chain(*list(zip(
                map(lambda e: nn.Linear(*e), pairs), 
                itertools.repeat(getattr(nn, activation)())
            ))))[:-1]
            self.x_seq = nn.Sequential(*chain)

            steps = [feature_dims+t_dim+n_aug, *layers, 1]
            pairs = zip(steps, steps[1:])
            chain = list(itertools.chain(*list(zip(
                map(lambda e: nn.Linear(*e), pairs), 
                itertools.repeat(getattr(nn, activation)())
            ))))[:-1]
            self.m_seq = nn.Sequential(*chain)
            if m_zero_weight_init:
                self.m_seq.apply(initialize_weights_to_zero)

            def seq(self, x):
                return torch.cat((self.x_seq(x[...,:-1]), self.m_seq(x)), dim=-1)
            self.seq = seq.__get__(self)

        else:
            steps = [feature_dims+t_dim+n_aug, *layers, feature_dims]
            pairs = zip(steps, steps[1:])
            chain = list(itertools.chain(*list(zip(
                map(lambda e: nn.Linear(*e), pairs), 
                itertools.repeat(getattr(nn, activation)())
            ))))[:-1]

            # self.chain = chain
            self.seq = (nn.Sequential(*chain))

        self.alpha = nn.Parameter(torch.tensor(scales, requires_grad=True).float()) if scales is not None else None
        self.n_aug = n_aug       
        self.zero_gate = zero_gate
        
        self.unif_velo_strict = unif_velo_strict
        if unif_velo_strict:
            # assert unif_velo, "Cannot set unif_velo_strict to True without unif_velo."
            unif_velo = True
        self.unif_velo = unif_velo
        self.unif_velo_t = unif_velo_t
        if unif_velo_t:
            assert unif_velo, "Cannot set unif_velo_t to True without unif_velo."
        if unif_velo:
            if unif_velo_t:
                self.mean_velo_logit_network = nn.Sequential(
                    nn.Linear(1, 8), 
                    getattr(nn, activation)(), 
                    nn.Linear(8, 8),
                    getattr(nn, activation)(),
                    nn.Linear(8, 1)
                )
            else:
                self.mean_velo_logit = nn.Parameter(torch.tensor(0.).float(), requires_grad=True)
        
    def mean_velocity(self, t):
        assert self.unif_velo, "Cannot call mean_velocity without unif_velo."
        if self.unif_velo_t:
            return torch.exp(self.mean_velo_logit_network(t))
        return torch.exp(self.mean_velo_logit)

    def forward(self, t, x): #NOTE the forward pass when we use torchdiffeq must be forward(self,t,x)
        if self.zero_gate:
            m = x[...,-1]
        zero = torch.tensor([0]).cuda() if x.is_cuda else torch.tensor([0])
        zeros = zero.repeat(x.size()[0],self.n_aug)
        if self.time_homogeneous:
            aug = torch.cat((x,zeros),dim=1)
        else:
            time = t.repeat(x.size()[0],1)
            aug = torch.cat((x,time,zeros),dim=1)
        x = self.seq(aug)
        if self.alpha is not None:
            z = torch.randn(x.size(),requires_grad=False).cuda() if x.is_cuda else torch.randn(x.size(),requires_grad=False)
        dxdt = x + z*self.alpha[int(t-1)] if self.alpha is not None else x
        if self.zero_gate:
            dxdt[m == 0., -1] = 0.

        if self.unif_velo_strict:
            norms = dxdt[...,:-1].norm(dim=-1, keepdim=True)
            dxdt1 = torch.cat((dxdt[...,:-1] / norms * torch.exp(self.mean_velo_logit), dxdt[...,-1].unsqueeze(-1)), dim=-1)
            return dxdt1
        
        return dxdt
    
    def forward_x(self, t, x): # this x does not include m, so need to concat zeros
        x = torch.cat((x, torch.zeros_like(x[..., -1:])), dim=-1)
        return self.forward(t, x)[...,:-1]
    
    def forward_m(self, t, x):
        return self.forward(t, x)[...,-1:]

# %% ../nbs/03_models.ipynb 4
import torch
def make_model(
    feature_dims=5,
    layers=[64],
    # output_dims=5,
    activation='ReLU',
    which='ode',
    method='rk4',
    rtol=None,
    atol=None,
    scales=None,
    n_aug=2,
    noise_type='diagonal', sde_type='ito',
    use_norm=False,
    use_cuda=False,
    # in_features=2, out_features=2, gunc=None,
    m_transform='exp',
    dt=0.1,
    time_homogeneous=False,
    unif_velo=False,
    unif_velo_strict=False,
    uni_velo_t=False,
    separate_network_m=False,
    m_zero_weight_init=True,
):
    """
    Creates the 'ode' model or 'sde' model or the Geodesic Autoencoder. 
    See the parameters of the respective classes.
    """
    assert use_norm == False, "This way of energy loss is removed. Now using energy loss."
    if m_transform == 'exp':
        m_trans = torch.exp
        m_init = 0.
    elif m_transform == 'relu':
        m_trans = torch.nn.functional.relu
        m_init = 1.
    else:
        raise ValueError('m_transform must be exp or relu')
    if which == 'ode':
        ode = ToyODE(feature_dims, layers, activation,scales,n_aug, time_homogeneous=time_homogeneous, unif_velo=unif_velo, unif_velo_strict=unif_velo_strict, unif_velo_t=uni_velo_t, separate_network_m=separate_network_m, m_zero_weight_init=m_zero_weight_init)
        model = ToyModel(ode,method,rtol, atol)
    elif which == 'sde':
        raise NotImplementedError("SDE model not implemented.")
        # ode = ToyODE(feature_dims, layers, activation,scales,n_aug)
        # model = ToySDEModel(
        #     ode, method, noise_type, sde_type,
        #     in_features=in_features, out_features=out_features, gunc=gunc
        # )
    elif which == 'ode_growth_rate':
        # ode = ToyODE(feature_dims + 1, layers, activation,scales,n_aug, zero_gate=True)
        ode = ToyODE(feature_dims + 1, layers, activation,scales,n_aug, zero_gate=False, time_homogeneous=time_homogeneous, unif_velo=unif_velo, unif_velo_strict=unif_velo_strict, unif_velo_t=uni_velo_t, separate_network_m=separate_network_m, m_zero_weight_init=m_zero_weight_init)
        model = GrowthRateModel(ode,method,rtol, atol, m_transform=m_trans, m_init=m_init)
    elif which == 'sde_growth_rate':
        assert method in ['adjoint_reversible_heun', 'euler', 'euler_heun', 'heun', 'log_ode', 'midpoint', 'milstein', 'reversible_heun', 'srk'] # rk4 not supported.
        ode = ToyODE(feature_dims + 1, layers, activation,scales,n_aug, zero_gate=True, time_homogeneous=time_homogeneous, unif_velo=unif_velo, unif_velo_strict=unif_velo_strict, unif_velo_t=uni_velo_t, separate_network_m=separate_network_m, m_zero_weight_init=m_zero_weight_init)
        gunc = ToyODE(feature_dims + 1, layers, activation,scales,n_aug, zero_gate=False, time_homogeneous=time_homogeneous, unif_velo=unif_velo, unif_velo_strict=unif_velo_strict, unif_velo_t=uni_velo_t, separate_network_m=separate_network_m, m_zero_weight_init=m_zero_weight_init)
        model = GrowthRateSDEModel(
            ode, method, noise_type, sde_type,
            in_features=feature_dims + 1, out_features=feature_dims + 1, gunc=gunc, dt=dt, m_transform=m_trans, m_init=m_init,
        )
    else:
        raise ValueError(f"Model {which} not recognized.")
        # model = ToyGeo(feature_dims, layers, output_dims, activation)
    if use_cuda:
        model.cuda()
    return model 

# %% ../nbs/03_models.ipynb 5
import itertools
import torch.nn as nn
from torch.nn  import functional as F 

class Autoencoder(nn.Module):
    """ 
    Geodesic Autoencoder
    
    encoder_layers (list of int) default '[100, 100, 20]': encoder_layers[0] is the feature dimension, and encoder_layers[-1] the embedded dimension.
    decoder_layers (list of int) defaulf '[20, 100, 100]': decoder_layers[0] is the embbeded dim and decoder_layers[-1] the feature dim.
    activation (torch.nn) default '"Tanh"': activation function applied in between layers.
    use_cuda (bool) default to False: Whether to use GPU or CPU.
    
    Method
    encode
        forward pass of the encoder
        x (torch.tensor): observations
        Return:
        the encoded observations
    decode
        forward pass of the decoder
        z (torch.tensor): embedded observations
        Return:
        the decoded observations
    forward (Callable):
        full forward pass, encoder and decoder
        x (torch.tensor): observations
        Return:
        denoised observations
    """

    def __init__(
        self,
        encoder_layers = [100, 100, 20],
        decoder_layers = [20, 100, 100],
        activation = 'Tanh',
        use_cuda = False
    ):        
        super(Autoencoder, self).__init__()
        if decoder_layers is None:
            decoder_layers = [*encoder_layers[::-1]]
        device = 'cuda' if use_cuda else 'cpu'
        
        encoder_shapes = list(zip(encoder_layers, encoder_layers[1:]))
        decoder_shapes = list(zip(decoder_layers, decoder_layers[1:]))
        
        encoder_linear = list(map(lambda a: nn.Linear(*a), encoder_shapes))
        decoder_linear = list(map(lambda a: nn.Linear(*a), decoder_shapes))
        
        encoder_riffle = list(itertools.chain(*zip(encoder_linear, itertools.repeat(getattr(nn, activation)()))))[:-1]
        encoder = nn.Sequential(*encoder_riffle).to(device)
        
        decoder_riffle = list(itertools.chain(*zip(decoder_linear, itertools.repeat(getattr(nn, activation)()))))[:-1]

        decoder = nn.Sequential(*decoder_riffle).to(device)
        self.encoder = encoder
        self.decoder = decoder

        
    
    def encode(self, x):
        return self.encoder(x)

    def decode(self, z):
        return self.decoder(z)

    def forward(self, x):
        z = self.encoder(x)
        return self.decoder(z)

# %% ../nbs/03_models.ipynb 6
adjoint = True
if adjoint:
    from torchdiffeq import odeint_adjoint as odeint
else:
    from torchdiffeq import odeint
import os, math, numpy as np
import torch
import torch.nn as nn
class ToyModel(nn.Module):
    """ 
    Neural ODE
        func (nn.Module): The network modeling the derivative.
        method (str) defaulf '"rk4"': any methods from torchdiffeq.
        rtol (NoneType | float): the relative tolerance of the ODE solver.
        atol (NoneType | float): the absolute tolerance. of the ODE solver.
        use_norm (bool): if True keeps the norm of func.
        norm (list of torch.tensor): the norm of the derivative.
        
        Method
        forward (Callable)
            x (torch.tensor): the initial sample
            t (torch.tensor) time points where we suppose x is from t[0]
            return the last sample or the whole seq.      
    """
    
    def __init__(self, func, method='rk4', rtol=None, atol=None, use_norm=False, use_norm_m=False):
        super(ToyModel, self).__init__()        
        self.func = func
        self.method = method
        self.rtol=rtol
        self.atol=atol
        if use_norm or use_norm_m:
            raise ValueError("use_norm and use_norm_m are no longer used. Now computing the energy penalty is outside the model.")
        # self.use_norm = use_norm
        # self.use_norm_m = use_norm_m
        # self.norm=[]
        # self.norm_m = []

    """
    Xingzhi: changed the energy penalty to being computed outside the model.
    """
    def forward(self, x, t, return_whole_sequence=False):

        # if self.use_norm or self.use_norm_m:
        #     for time in t: 
        #         """
        #         Xingzhi: This looks weird to me. it loops through time but only uses the initial x.
        #         I see that it might be an approximation because of the memory burden to save each intermediate x.
        #         Besides, putting a list of norms and relying on the outer code (the training loop) to reset it is dangerous, but I'll not change it.
        #         """
        #         dxdt = self.func(time,x)
        #         if self.use_norm:
        #             self.norm.append(torch.linalg.norm(dxdt).pow(2)) 
        #         if self.use_norm_m:
        #             self.norm_m.append(torch.square(dxdt[...,-1]).mean())

        kwargs = {'method': self.method}
        if self.atol is not None:
            kwargs['atol'] = self.atol
        if self.rtol is not None:
            kwargs['rtol'] = self.rtol


        x = odeint(self.func, x, t, **kwargs)

       
        x = x[-1] if not return_whole_sequence else x
        return x

# %% ../nbs/03_models.ipynb 7
from torchdiffeq import odeint_adjoint as odeint
import os, math, numpy as np
import torch
import torch.nn as nn
import torchsde

class ToySDEModel(nn.Module):
    """ 
    Neural SDE model
        func (nn.Module): drift term.
        genc (nn.Module): diffusion term.
        method (str): method of the SDE solver.
        
        Method
        forward (Callable)
            x (torch.tensor): the initial sample
            t (torch.tensor) time points where we suppose x is from t[0]
            return the last sample or the whole seq.  
    """
    
    def __init__(self, func, method='euler', noise_type='diagonal', sde_type='ito', 
    in_features=2, out_features=2, gunc=None, dt=0.1):
        super(ToySDEModel, self).__init__()        
        self.func = func
        self.method = method
        self.noise_type = noise_type
        self.sde_type = sde_type
        if gunc is None:
            self._gunc_args = 'y'
            self.gunc = nn.Linear(in_features, out_features)
        else:
            self._gunc_args = 't,y'
            self.gunc = gunc

        self.dt = dt
        
    def f(self, t, y):
        return self.func(t, y)

    def g(self, t, y):
        return self.gunc(t, y) if self._gunc_args == 't,y' else self.gunc(y)
        return 0.3 * torch.sigmoid(torch.cos(t) * torch.exp(-y))

    def forward(self, x, t, return_whole_sequence=False, dt=None):
        dt = self.dt if self.dt is not None else 0.1 if dt is None else dt        
        x = torchsde.sdeint(self, x, t, method=self.method, dt=dt)
       
        x = x[-1] if not return_whole_sequence else x
        return x

# %% ../nbs/03_models.ipynb 8
if adjoint:
    from torchdiffeq import odeint_adjoint as odeint

    def find_parameters(module):

        assert isinstance(module, nn.Module)

        # If called within DataParallel, parameters won't appear in module.parameters().
        if getattr(module, '_is_replica', False):

            def find_tensor_attributes(module):
                tuples = [(k, v) for k, v in module.__dict__.items() if torch.is_tensor(v) and v.requires_grad]
                return tuples

            gen = module._named_members(get_members_fn=find_tensor_attributes)
            return [param for _, param in gen]
        else:
            return list(module.parameters())

else:
    from torchdiffeq import odeint

import os, math, numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
class GrowthRateModel(ToyModel):
    """
    Last feature dim is the growth rate / mass.
    """
    def __init__(self, func, method='rk4', rtol=None, atol=None, use_norm=False, m_init=1., m_transform=lambda x: x):
        super().__init__(func, method, rtol, atol, use_norm)
        self.m_init = m_init
        self.m_transform = m_transform
    
    def forward(self, x, t, return_whole_sequence=False, m0=None):
        if m0 is None:
            m0 = torch.full((x.size()[0], 1), self.m_init, dtype=x.dtype, device=x.device)
        elif m0.ndim == 1:
            m0 = m0.unsqueeze(1)
        xm = torch.cat((x,m0),dim=1)
        if self.func.separate_network_m:
            kwargs = {'method': self.method}
            if self.atol is not None:
                kwargs['atol'] = self.atol
            if self.rtol is not None:
                kwargs['rtol'] = self.rtol
            m = odeint(self.func, xm, t, **kwargs)[...,-1]
            if adjoint:
                kwargs['adjoint_params'] = find_parameters(self.func.x_seq)
            x = odeint(self.func.forward_x, x, t, **kwargs)
            if return_whole_sequence:
                return x, self.m_transform(m)
            else:
                return x[-1], self.m_transform(m)[-1]

        else:
            x = super().forward(xm, t, return_whole_sequence)
            return x[...,:-1], self.m_transform(x[...,-1])

# %% ../nbs/03_models.ipynb 9
class GrowthRateSDEModel(ToySDEModel):
    def __init__(self, func, method='euler', noise_type='diagonal', sde_type='ito',
                 in_features=2, out_features=2, gunc=None, dt=0.1, m_init=0., m_transform=lambda x: x):
        super().__init__(func, method, noise_type, sde_type, in_features, out_features, gunc, dt)
        self.m_init = m_init
        self.m_transform = m_transform
    
    def forward(self, x, t, return_whole_sequence=False, m0=None, dt=None):
        if m0 is None:
            m0 = torch.full((x.size()[0], 1), self.m_init, dtype=x.dtype, device=x.device)
        elif m0.ndim == 1:
            m0 = m0.unsqueeze(1)
        xm = torch.cat((x,m0),dim=1)
        x = super().forward(xm, t, return_whole_sequence, dt)
        return x[...,:-1], self.m_transform(x[...,-1])

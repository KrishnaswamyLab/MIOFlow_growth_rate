# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_losses.ipynb.

# %% auto 0
__all__ = ['hard_softmax', 'MMD_loss', 'OT_loss', 'UOT_loss', 'normalize_by_sum', 'density_specified_OT_loss', 'Density_loss',
           'Local_density_loss', 'EnergyLossSeq', 'EnergyLossGrowthRateSeq', 'EnergyLoss', 'EnergyLossGrowthRate',
           'UnifVeloLossSeq', 'UnifVeloLossGrowthRateSeq', 'UnifVeloLoss', 'UnifVeloLossGrowthRate']

# %% ../nbs/01_losses.ipynb 3
import os, math, numpy as np
import torch
import torch.nn as nn

class MMD_loss(nn.Module):
    '''
    https://github.com/ZongxianLee/MMD_Loss.Pytorch/blob/master/mmd_loss.py
    '''
    def __init__(self, kernel_mul = 2.0, kernel_num = 5):
        super(MMD_loss, self).__init__()
        self.kernel_num = kernel_num
        self.kernel_mul = kernel_mul
        self.fix_sigma = None
        return
    
    def guassian_kernel(self, source, target, kernel_mul=2.0, kernel_num=5, fix_sigma=None):
        n_samples = int(source.size()[0])+int(target.size()[0])
        total = torch.cat([source, target], dim=0)
        total0 = total.unsqueeze(0).expand(int(total.size(0)), int(total.size(0)), int(total.size(1)))
        total1 = total.unsqueeze(1).expand(int(total.size(0)), int(total.size(0)), int(total.size(1)))
        L2_distance = ((total0-total1)**2).sum(2) 
        if fix_sigma:
            bandwidth = fix_sigma
        else:
            bandwidth = torch.sum(L2_distance.data) / (n_samples**2-n_samples)
        bandwidth /= kernel_mul ** (kernel_num // 2)
        bandwidth_list = [bandwidth * (kernel_mul**i) for i in range(kernel_num)]
        kernel_val = [torch.exp(-L2_distance / bandwidth_temp) for bandwidth_temp in bandwidth_list]
        return sum(kernel_val)

    def forward(self, source, target):
        batch_size = int(source.size()[0])
        kernels = self.guassian_kernel(source, target, kernel_mul=self.kernel_mul, kernel_num=self.kernel_num, fix_sigma=self.fix_sigma)
        XX = kernels[:batch_size, :batch_size]
        YY = kernels[batch_size:, batch_size:]
        XY = kernels[:batch_size, batch_size:]
        YX = kernels[batch_size:, :batch_size]
        loss = torch.mean(XX + YY - XY -YX)
        return loss

# %% ../nbs/01_losses.ipynb 4
import ot
import torch.nn as nn
import torch
import numpy as np
class OT_loss(nn.Module):
    _valid = 'emd sinkhorn sinkhorn_knopp_unbalanced'.split()

    def __init__(self, which='emd', use_cuda=True, reg=0.5, reg_m=0.5):
        if which not in self._valid:
            raise ValueError(f'{which} not known ({self._valid})')
        elif which == 'emd':
            self.fn = lambda m, n, M: ot.emd(m, n, M)
        elif which == 'sinkhorn':
            self.fn = lambda m, n, M : ot.sinkhorn(m, n, M, reg) # maybe use 0.5 for regularization.
        elif which == 'sinkhorn_knopp_unbalanced':
            self.fn = lambda m, n, M : ot.unbalanced.sinkhorn_knopp_unbalanced(m, n, M, reg, reg_m) # keep in mind these regularization parameters and maybe test if they converge.
        else:
            pass
        self.use_cuda=use_cuda

    def __call__(self, source, target, use_cuda=None):
        if use_cuda is None:
            use_cuda = self.use_cuda
        mu = torch.from_numpy(ot.unif(source.size()[0]))
        nu = torch.from_numpy(ot.unif(target.size()[0]))
        M = torch.cdist(source, target)**2
        pi = self.fn(mu, nu, M.detach().cpu())
        if type(pi) is np.ndarray:
            pi = torch.tensor(pi)
        elif type(pi) is torch.Tensor:
            pi = pi.clone().detach()
        pi = pi.cuda() if use_cuda else pi
        M = M.to(pi.device)
        loss = torch.sum(pi * M)
        return loss

# %% ../nbs/01_losses.ipynb 5
import ot
import torch.nn as nn
import torch
import numpy as np
class UOT_loss(nn.Module):
    _valid = 'mm_unbalanced'.split()

    def __init__(self, which='mm_unbalanced', use_cuda=True, reg_m_l2=[5., 5.], detach_M=False, detach_m=False, detach_plan=True, use_uniform=False, marginal_match_dim=1):
        if which not in self._valid:
            raise ValueError(f'{which} not known ({self._valid})')
        elif which == 'mm_unbalanced':
            self.fn = lambda m, n, M: ot.unbalanced.mm_unbalanced(m, n, M, reg_m_l2, div='l2')
        else:
            pass
        self.detach_M = detach_M
        self.detach_m = detach_m
        self.detach_plan = detach_plan
        self.use_uniform = use_uniform
        assert marginal_match_dim in [0, 1]
        self.marginal_match_dim = marginal_match_dim

    def __call__(self, source, target, source_density, target_density):
        assert source_density.shape[0] == source.shape[0] and target_density.shape[0] == target.shape[0]
        mu = source_density
        nu = target_density
        M = ot.dist(source, target)
        if self.detach_M:
            M1 = M.detach()
        else:
            M1 = M
        if self.detach_m:
            mu1 = mu.detach()
            nu1 = nu.detach()
        else:
            mu1 = mu
            nu1 = nu
        if self.use_uniform:
            mu1 = target_density # the target is uniform times n_samples, and we match that.
        plan = self.fn(mu1, nu1, M1)
        if self.detach_plan:
            plan = plan.detach()
        ot_loss = (plan * M).sum()
        marginal_transported = plan.sum(dim=self.marginal_match_dim)
        marginal_loss = nn.functional.mse_loss(marginal_transported, mu)
        self.plan = plan
        return ot_loss, marginal_loss

# %% ../nbs/01_losses.ipynb 6
import torch

def normalize_by_sum(tensor, dim=-1, eps=1e-8):
    sum_along_dim = torch.sum(tensor, dim=dim, keepdim=True)
    sum_along_dim = sum_along_dim + eps  # Add epsilon to avoid division by zero
    return tensor / sum_along_dim

# %% ../nbs/01_losses.ipynb 7
import torch.nn.functional as F
hard_softmax = F.softmax
# def hard_softmax(input, dim=None):
#     zero_mask = (input.sum(dim=dim, keepdim=True) == 0)
#     input = torch.where(zero_mask, torch.ones_like(input), input)
#     sum_hardsigmoid = torch.sum(input, dim=dim, keepdim=True)
#     softmax_output = input / sum_hardsigmoid
    
#     return softmax_output

# def hard_softmax(input, dim=None, expand_factor=1., shift=0., func=lambda x: x, threshold=None):
#     # func = F.hardsigmoid
#     # Apply hardsigmoid to the input
#     if expand_factor != 1.:
#         input = input * expand_factor
#     if shift != 0.:
#         input = input + shift
#     hardsigmoid_input = func(input)

#     if threshold is not None:
#         hardsigmoid_input = torch.where(hardsigmoid_input < threshold, torch.zeros_like(hardsigmoid_input), hardsigmoid_input)

#     # Identify rows/columns that are all zeros
#     zero_mask = (hardsigmoid_input.sum(dim=dim, keepdim=True) == 0)
    
#     # For rows/columns that are all zeros, set all values to 1
#     hardsigmoid_input = torch.where(zero_mask, torch.ones_like(hardsigmoid_input), hardsigmoid_input)
    
#     # Normalize by the sum along the specified dimension
#     sum_hardsigmoid = torch.sum(hardsigmoid_input, dim=dim, keepdim=True)
#     softmax_output = hardsigmoid_input / sum_hardsigmoid
    
#     return softmax_output

# %% ../nbs/01_losses.ipynb 8
import ot
import torch.nn as nn
import torch
import numpy as np
class density_specified_OT_loss(nn.Module):
    """_summary_
    Only allowing balanced Sinkhorn, because it is the only one with stable backprop.

    Args:
        nn (_type_): _description_

    Raises:
        ValueError: _description_

    Returns:
        _type_: _description_
    """
    # _valid = 'emd sinkhorn sinkhorn_knopp_unbalanced'.split()
    _valid = 'sinkhorn'.split()

    def __init__(self, which='sinkhorn', reg=0.1, reg_m=1.0, take_softmax=True, detach_M_ot=False, use_hard_softmax=True, threshold=None):
        if which not in self._valid:
            raise ValueError(f'{which} not known ({self._valid})')
        elif which == 'sinkhorn':
            self.fn = lambda m, n, M : ot.sinkhorn2(m, n, M, reg) # maybe use 0.5 for regularization.
        # elif which == 'sinkhorn_knopp_unbalanced':
        #     self.fn = lambda m, n, M : (ot.unbalanced.sinkhorn_knopp_unbalanced(m, n, M, reg, reg_m) * M).sum() # keep in mind these regularization parameters and maybe test if they converge.
        #     print("WARNING: ot.unbalanced.sinkhorn_knopp_unbalanced chosen -- Can it back propagate density?")
        # elif which == 'emd':
        #     self.fn = lambda m, n, M: ot.emd2(m, n, M)
        #     print("WARNING: ot.emd chosen -- Can it back propagate density?")
        else:
            pass
        if take_softmax:
            if use_hard_softmax:
                self.softmax = lambda x: hard_softmax(x, dim=-1)
            else:
                self.softmax = lambda x: nn.functional.softmax(x, dim=-1)
        else:
            self.softmax = lambda x: x
        self.detach_M_ot = detach_M_ot

    def __call__(self, source, target, source_density, target_density=None):
        # mu = torch.from_numpy(ot.unif(source.size()[0]))
        assert source_density.shape[0] == source.shape[0]
        mu = source_density
        if target_density is None:
            nu = torch.tensor(ot.unif(target.size()[0]), device=source.device, dtype=source.dtype)
        else:
            assert target_density.shape[0] == target.shape[0]
            nu = target_density
        mu = self.softmax(mu)
        nu = self.softmax(nu)
        M = torch.cdist(source, target)#**2 # strangely this squaring prevents backprop through the density. 
        if self.detach_M_ot:
            M = M.detach()
        loss = self.fn(mu, nu, M)
        return loss

# %% ../nbs/01_losses.ipynb 9
import torch.nn as nn
import torch
class Density_loss(nn.Module):
    def __init__(self, hinge_value=0.01, use_softmax=False, use_hard_softmax=False):
        self.hinge_value = hinge_value
        self.use_softmax = use_softmax
        if use_softmax:
            if use_hard_softmax:
                self.softmax = lambda x: hard_softmax(x, dim=-1)
            else:
                self.softmax = lambda x: nn.functional.softmax(x, dim=-1)
        else:
            # self.softmax = lambda x: x / x.size(-1) # normalize by batch size.
            self.softmax = normalize_by_sum
    def __call__(self, source, target, groups = None, to_ignore = None, top_k = 5, source_weights=None, target_weights=None):

        if groups is not None:
            # for global loss
            c_dist_list = []
            for i in range(1, len(groups)):
                if groups[i] != to_ignore:
                    if source_weights is None:
                        source_weights_i = torch.ones(source[i].size(0), device=source[i].device, dtype=source[i].dtype)
                    else:
                        source_weights_i = source_weights[i]
                    source_weights_softmax_i = self.softmax(source_weights_i) * source_weights_i.shape[-1]
                    if target_weights is None:
                        target_weights_i = torch.ones(target[i].size(0), device=target[i].device, dtype=target[i].dtype)
                    else:
                        target_weights_i = target_weights[i]
                    target_weights_softmax_i = self.softmax(target_weights_i) * target_weights_i.shape[-1]
                    dist = torch.cdist(source[i], target[i])
                    weighted_dist = dist * source_weights_softmax_i.unsqueeze(-1) * target_weights_softmax_i.unsqueeze(0)
                    c_dist_list.append(weighted_dist)
            c_dist = torch.stack(c_dist_list)
            # NOTE: check if this should be 1 indexed
        else:
            if source_weights is None:
                source_weights = torch.ones(source.size(0), device=source.device, dtype=source.dtype)
            source_weights_softmax = self.softmax(source_weights) * source_weights.shape[-1]
            if target_weights is None:
                target_weights = torch.ones(target.size(0), device=target.device, dtype=target.dtype)
            target_weights_softmax = self.softmax(target_weights) * target_weights.shape[-1]
            # for local loss
            c_dist = torch.stack([
                torch.cdist(source, target) * source_weights_softmax.unsqueeze(-1) * target_weights_softmax.unsqueeze(0)
            ])
        values, _ = torch.topk(c_dist, top_k, dim=2, largest=False, sorted=False)
        values -= self.hinge_value
        values[values<0] = 0
        loss = torch.mean(values)
        return loss

# %% ../nbs/01_losses.ipynb 10
class Local_density_loss(nn.Module):
    def __init__(self):
        pass

    def __call__(self, sources, targets, groups, to_ignore, top_k = 5):
        # print(source, target)
        # c_dist = torch.cdist(source, target) 
        c_dist = torch.stack([
            torch.cdist(sources[i], targets[i]) 
            # NOTE: check if should be from range 1 or not.
            for i in range(1, len(groups))
            if groups[i] != to_ignore
        ])
        vals, inds = torch.topk(c_dist, top_k, dim=2, largest=False, sorted=False)
        values = vals[inds[inds]]
        loss = torch.mean(values)
        return loss

# %% ../nbs/01_losses.ipynb 11
class EnergyLossSeq(nn.Module):
    def __init__(self):
        pass

    def __call__(self, func, xtseq, t):
        dxdt = torch.stack([func(t[i], xtseq[i]) for i in range(len(t))])
        return torch.square(dxdt).mean()
    
class EnergyLossGrowthRateSeq(nn.Module):
    def __init__(self, weighted=True, detach_m=False, use_softmax=False, use_hard_softmax=False):
        self.weighted = weighted
        self.detach_m = detach_m
        self.use_softmax = use_softmax
        if use_softmax:
            if use_hard_softmax:
                self.softmax = lambda x: hard_softmax(x, dim=-1)
            else:
                self.softmax = lambda x: nn.functional.softmax(x, dim=-1)
        else:
            # self.softmax = lambda x: x / x.size(-1)
            self.softmax = normalize_by_sum

    def __call__(self, func, xtseq, mtseq, t):
        """Returns the energy wrt the x and m curves separately.

        Args:
            func (_type_): _description_
            xtseq (_type_): _description_
            mtseq (_type_): _description_
            t (_type_): _description_

        Returns:
            _type_: _description_
        """
        xmseq = torch.cat([xtseq, mtseq.unsqueeze(-1)], dim=-1)
        dxdt = torch.stack([func(t[i], xmseq[i]) for i in range(len(t))])
        if self.weighted:
            masses = self.softmax(mtseq) * mtseq.shape[-1]
            if self.detach_m:
                masses = masses.detach()
            dxdt = dxdt * masses.unsqueeze(-1) # weighted by mass
        return torch.square(dxdt[...,:-1]).mean(), torch.square(dxdt[...,-1]).mean()
    
class EnergyLoss(nn.Module):
    def __init__(self):
        pass

    def __call__(self, func, x, t): # should use the current t. i.e. t_seq[-1]
        dxdt = func(t, x)
        return torch.square(dxdt).mean()

class EnergyLossGrowthRate(nn.Module):
    def __init__(self, weighted=True, detach_m=False, use_softmax=False, use_hard_softmax=False):
        self.weighted = weighted
        self.detach_m = detach_m
        self.use_softmax = use_softmax
        if use_softmax:
            if use_hard_softmax:
                self.softmax = lambda x: hard_softmax(x, dim=-1)
            else:
                self.softmax = lambda x: nn.functional.softmax(x, dim=-1)
        else:
            # self.softmax = lambda x: x / x.size(-1)
            self.softmax = normalize_by_sum

    def __call__(self, func, x, m, t):
        xm = torch.cat([x, m.unsqueeze(-1)], dim=-1)
        dxdt = func(t, xm)
        if self.weighted:
            masses = self.softmax(m) * m.shape[-1]
            if self.detach_m:
                masses = masses.detach()
            dxdt = dxdt * masses.unsqueeze(-1) # weighted by mass
        return torch.square(dxdt[...,:-1]).mean(), torch.square(dxdt[...,-1]).mean()

# %% ../nbs/01_losses.ipynb 12
# not going to penalize m velo because it is growth rate.
class UnifVeloLossSeq(nn.Module):
    def __init__(self, square=False, topk=None):
        self.square = square
        self.topk = topk

    def __call__(self, func, xtseq, t):
        dxdt = torch.stack([func(t[i], xtseq[i]) for i in range(len(t))])
        mean_velo = func.mean_velocity(t.unsqueeze(-1))
        norms = dxdt.norm(dim=-1)
        if self.square:
            res = torch.square(norms - mean_velo)
            # return torch.square(norms - mean_velo).mean()
        else:
            # return torch.abs(norms - mean_velo).mean()
            res = torch.abs(norms - mean_velo)
        if self.topk is not None:
            values, _ = torch.topk(res, self.topk, dim=0, largest=True, sorted=True)
            return values.mean()
        else:
            return res.mean()
    
class UnifVeloLossGrowthRateSeq(nn.Module):
    def __init__(self, weighted=True, detach_m=False, use_softmax=False, use_hard_softmax=False, square=False, topk=None):
        self.weighted = weighted
        self.detach_m = detach_m
        self.use_softmax = use_softmax
        if use_softmax:
            if use_hard_softmax:
                self.softmax = lambda x: hard_softmax(x, dim=-1)
            else:
                self.softmax = lambda x: nn.functional.softmax(x, dim=-1)
        else:
            # self.softmax = lambda x: x / x.size(-1)
            self.softmax = normalize_by_sum
        self.square = square
        self.topk = topk
    def __call__(self, func, xtseq, mtseq, t):
        """Returns the UnifVelo wrt the x and m curves separately.

        Args:
            func (_type_): _description_
            xtseq (_type_): _description_
            mtseq (_type_): _description_
            t (_type_): _description_

        Returns:
            _type_: _description_
        """
        xmseq = torch.cat([xtseq, mtseq.unsqueeze(-1)], dim=-1)
        dxdt = torch.stack([func(t[i], xmseq[i]) for i in range(len(t))])
        mean_velo = func.mean_velocity(t.unsqueeze(-1))
        if self.weighted:
            masses = self.softmax(mtseq) * mtseq.shape[-1]
            if self.detach_m:
                masses = masses.detach()
            dxdt = dxdt * masses.unsqueeze(-1) # weighted by mass
        # return torch.square(dxdt[...,:-1]).sum(axis=-1).var(), torch.square(dxdt[...,-1]).var()
        norms = dxdt[...,:-1].norm(dim=-1)
        if self.square:
            res = torch.square(norms - mean_velo)
        else:
            res = torch.abs(norms - mean_velo)
        if self.topk is not None:
            values, _ = torch.topk(res, self.topk, dim=0, largest=True, sorted=True)
            return values.mean()
        else:
            return res.mean()
    
class UnifVeloLoss(nn.Module):
    def __init__(self, square=False, topk=None):
        self.square = square
        self.topk = topk

    def __call__(self, func, x, t): # should use the current t. i.e. t_seq[-1]
        dxdt = func(t, x)
        mean_velo = func.mean_velocity(torch.tensor([t], dtype=x.dtype, device=x.device))
        if self.square:
            res = torch.square(dxdt.norm(dim=-1) - mean_velo)
        else:
            res = torch.abs(dxdt.norm(dim=-1) - mean_velo)
        if self.topk is not None:
            values, _ = torch.topk(res, self.topk, dim=0, largest=True, sorted=True)
            return values.mean()
        else:
            return res.mean()

class UnifVeloLossGrowthRate(nn.Module):
    def __init__(self, weighted=True, detach_m=False, use_softmax=False, use_hard_softmax=False, square=False, topk=None):
        self.weighted = weighted
        self.detach_m = detach_m
        self.use_softmax = use_softmax
        if use_softmax:
            if use_hard_softmax:
                self.softmax = lambda x: hard_softmax(x, dim=-1)
            else:
                self.softmax = lambda x: nn.functional.softmax(x, dim=-1)
        else:
            # self.softmax = lambda x: x / x.size(-1)
            self.softmax = normalize_by_sum
        self.square = square
        self.topk = topk

    def __call__(self, func, x, m, t):
        xm = torch.cat([x, m.unsqueeze(-1)], dim=-1)
        dxdt = func(t, xm)
        mean_velo = func.mean_velocity(torch.tensor([t], dtype=x.dtype, device=x.device))
        if self.weighted:
            masses = self.softmax(m) * m.shape[-1]
            if self.detach_m:
                masses = masses.detach()
            dxdt = dxdt * masses.unsqueeze(-1) # weighted by mass
        if self.square:
            res = torch.square(dxdt[...,:-1].norm(dim=-1) - mean_velo)
        else:
            res = torch.abs(dxdt[...,:-1].norm(dim=-1) - mean_velo)
        if self.topk is not None:
            values, _ = torch.topk(res, self.topk, dim=0, largest=True, sorted=True)
            return values.mean()
        else:
            return res.mean()

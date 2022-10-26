# AUTOGENERATED! DO NOT EDIT! File to edit: ../09_geo.ipynb.

# %% auto 0
__all__ = ['DiffusionDistance', 'DiffusionAffinity', 'DiffusionMap', 'PhateDistance', 'old_DiffusionDistance', 'setup_distance']

# %% ../09_geo.ipynb 3
import graphtools
from scipy.sparse import csr_matrix
import numpy as np
from sklearn.metrics.pairwise import pairwise_distances

class DiffusionDistance:
    """
    class DiffusionDistance        
        X (np.array) data 
        t_max (int), 2^t_max is the max scale of the Diffusion kernel
        knn (int) = 5 number of neighbors for the KNN in the alpha decay kernel construction, same default as in PHATE
        Anisotropy (int): the alpha in Coifman Lafon 2006, 1: double normalization 0: usual random walk
        log (bool) log(P) or not
        normalize (bool) min-max normalization of the distance matrix
        phate (bool) is PHATE op if true (should be the same as graphtool)
        
    """
   
    def __init__(self, t_max=5, knn=5, anisotropy=1, log=False, normalize=False, symmetrize=False) -> None:
        self.t_max = t_max
        self.knn = knn
        self.aniso = anisotropy
        self.log = log
        self.normalize = normalize
        self.symmetrize = symmetrize
        self.K = None
        self.P = None
        self.pi = None
        self.G = None    
            
    def compute_stationnary_distrib(self): 
        pi = np.sum(self.K, axis = 1)
        self.pi = pi/np.sum(pi)
        return self.pi
        
    def compute_custom_diffusion_distance(self): 
        P = self.P
        P_d = P if not self.log else csr_matrix((np.log(P.data),P.indices,P.indptr), shape=P.shape)
        G = pairwise_distances(P_d,P_d,metric='l1',n_jobs=-1)
                
        for t in range(1,self.t_max): 
            P = P @ P 
            if self.log==True:
                dist = pairwise_distances(P,P,metric='l1',n_jobs=-1)
                np.fill_diagonal(dist,1)
                dist = (-1)*np.log(dist)
            else:
                dist = pairwise_distances(P_d,P_d,metric='l1',n_jobs=-1)
            G = G + 2**(-t/2.0) * dist
        
        if self.log==True:
            dist = pairwise_distances(self.pi,self.pi,metric='l1',n_jobs=-1)
            np.fill_diagonal(dist,1)
            dist = (-1)*np.log(dist)
        else:
            dist = pairwise_distances(self.pi,self.pi,metric='l1',n_jobs=-1)     
        G = G + 2**(-(self.t_max+1)/2.0) * dist
        self.G = G if not self.normalize else (G - np.min(G))/(np.max(G)-np.min(G))
        return self.G

    def fit(self, X):
        graph = graphtools.Graph(X, knn=self.knn,anisotropy=self.aniso)
        self.K = graph.K
        self.P = graph.diff_op 
        self.compute_stationnary_distrib()
        self.compute_custom_diffusion_distance()       
        return self.G if not self.symmetrize else (self.G + np.transpose(self.G))/0.5

# %% ../09_geo.ipynb 4
import phate
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import eigs
import sklearn
import graphtools


class DiffusionAffinity:
    """
    class DiffusionAffinity        
        X (np.array) data 
        t_max (int), 2^t_max is the max scale of the Diffusion kernel
        knn (int) = 5 number of neighbors for the KNN in the alpha decay kernel construction, same default as in PHATE
        Anisotropy (int): the alpha in Coifman Lafon 2006, 1: double normalization 0: usual random walk
        t_diff (int) the power of the diffusion affinity matrix
        topeig (int) in the the top k eigenvalues to consider in the spectral decomposition
        
        return the l2 between the row of the affinity matrix A^t
    """
   
    def __init__(self, knn=5, anisotropy=0, t_diff=1, topeig=100) -> None:
        self.knn = knn
        self.aniso = anisotropy
        self.t_diff = t_diff
        self.topeig = topeig
        self.A = None
        self.G = None    
        
    def fit(self, X):
        self.graph = graphtools.Graph(X, knn=self.knn,anisotropy=self.aniso) 
        self.A = self.graph.diff_aff
        if self.t_diff ==1:
            self.G = sklearn.metrics.pairwise.pairwise_distances(self.A,self.A,metric='l2',n_jobs=-1)
        else:
            k = self.topeig if self.topeig < X.shape[0] else X.shape[0]-2
            w, v = eigs(self.A,k=k, which='LR')
            W = np.diag(w)
            A_t = np.real(v @ (W**self.t_diff) @ v.T)
            self.G = sklearn.metrics.pairwise.pairwise_distances(A_t,A_t,metric='l2',n_jobs=-1)
        return self.G

# %% ../09_geo.ipynb 5
import scipy
import graphtools

class DiffusionMap:
    """
    class DiffusionMap        
        X (np.array) data 
        t_max (int), 2^t_max is the max scale of the Diffusion kernel
        knn (int) = 5 number of neighbors for the KNN in the alpha decay kernel construction, same default as in PHATE
        Anisotropy (int): the alpha in Coifman Lafon 2006, 1: double normalization 0: usual random walk
        t_diff (int) the power of the diffusion affinity matrix
        topeig (int) in the the top k eigenvalues to consider in the spectral decomposition
        n_emb (int) the dimension of the emb space
        
        return the pairwise dist. in the diffusion map embedding space
        
    """
   
    def __init__(self, knn=5, anisotropy=0, t_diff=1, topeig=100, n_emb=10) -> None:
        self.knn = knn
        self.aniso = anisotropy
        self.t_diff = t_diff
        self.topeig = topeig
        self.n_emb = n_emb
        self.A = None
        self.G = None    
        
    def fit(self, X):
        self.graph = graphtools.Graph(X, knn=self.knn,anisotropy=self.aniso) 
        self.A = self.graph.diff_aff
        k = self.topeig if self.topeig < X.shape[0] else X.shape[0]-2
        w, v = eigs(self.A,k=k, which='LR')
        w, v = np.real(w), np.real(v)
        v = v/v[:,0,None]
        self.emb = np.vstack([(w[i]**self.t_diff)*v[:,i] for i in range(1,self.n_emb+1)])
        self.G = scipy.spatial.distance.pdist(self.emb.T)
        return self.G

# %% ../09_geo.ipynb 6
from sklearn.metrics.pairwise import pairwise_distances
import phate

class PhateDistance:
    """
    class PhateDistance     
        X (np.array) data 
        knn (int) = 5 number of neighbors for the KNN in the alpha decay kernel construction, same default as in PHATE
        Anisotropy (int): the alpha in Coifman Lafon 2006, 1: double normalization 0: usual random walk
        verbose (bool): verbose param. in PHATE
        
        return PHATE distance the L2 between Potential of Heat-diffusion
    """
   
    def __init__(self, knn=5, anisotropy=0,verbose=False) -> None:
        self.knn = knn
        self.aniso = anisotropy
        self.verbose = verbose
        
    def fit(self, X):
        graph = phate.PHATE(knn=self.knn, verbose=self.verbose, n_landmark=X.shape[0]).fit(X)
        self.diff_pot = graph.diff_potential 
        self.G = pairwise_distances(self.diff_pot,self.diff_pot,metric='l2',n_jobs=-1)
        return self.G

# %% ../09_geo.ipynb 7
import numpy as np
from scipy.spatial import distance_matrix

"""
class DiffusionDistance
    
    kernel
    X
    t_max
    stationnary_distrib
"""
class old_DiffusionDistance:
    kernel = None
    X = None
    t_max = None
    M = None
    P = None
    pi = None
    G = None
    def __init__(self, kernel, t_max) -> None:
        self.kernel= kernel
        self.t_max = t_max
     
    def compute_density_norm_matrix(self):
        K = self.kernel(self.X)
        Q = np.diag(np.sum(K, axis= 1))
        self.M = np.linalg.inv(Q).dot(K).dot(np.linalg.inv(Q))
        return self.M
    
    def compute_diffusion_Matrix(self): 
        D = np.diag(np.sum(self.M, axis= 1))
        self.P = np.linalg.inv(D).dot(self.M)
        return self.P
    
    def compute_stationnary_distrib(self): 
        pi = np.sum(self.M, axis = 1)/np.sum(self.M)
        self.pi = pi
        return self.pi
    
    def distance_matrix_Pt(self, t): 
        Pt = np.linalg.matrix_power(self.P, 2**(self.t_max-t))
        return distance_matrix(Pt,Pt,1)
        
    def compute_custom_diffusion_distance(self): 
        G = np.zeros((self.X.shape[0], self.X.shape[0]))
                
        for t in range(0,self.t_max): 
            G = G + 2**(-(self.t_max-t)/2) * self.distance_matrix_Pt(t)
        G = G + 2**(-(self.t_max+1)/2) * distance_matrix(self.pi[:, None],self.pi[:, None],1)

        self.G = G
        return self.G

    def fit(self, X):
        self.X = X
        self.compute_density_norm_matrix()
        self.compute_diffusion_Matrix()
        self.compute_stationnary_distrib()
        self.compute_custom_diffusion_distance()
        return self.G

# %% ../09_geo.ipynb 8
from sklearn.gaussian_process.kernels import RBF

def setup_distance(
    distance_type:str='gaussian',
    rbf_length_scale:float=0.5, t_max:int=5, knn:int=5
):
    _valid_distance_types = 'gaussian alpha_decay'.split()
    
    if distance_type == 'gaussian':
        # TODO: rename / retool old_DiffusionDistance into single
        #      DiffusionDistance class that "automagically" figures out
        #      implementation via input params
        dist = old_DiffusionDistance(RBF(rbf_length_scale), t_max=t_max)
    elif distance_type == 'alpha_decay':
        dist = DiffusionDistance(knn=knn, t_max=t_max)
    else:
        raise NotImplementedError(
            f'distance_type={distance_type} is not an implemented distance.\n'
            f'Please see {_valid_distance_types}'
        )
    return dist

import scipy as sp
from scipy.integrate import simps
from scipy import linalg
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from spectrum import *
from copy import deepcopy
#these are 'probalists', turns out to matter in order to match van der
#Marel & Franx 1993
from numpy.polynomial.hermite_e import HermiteE as H
import re


__all__ = ["RescaleModel","Chain","get_cc","metro_hast"]

debug = True


class RescaleModel(object):
    """
    This model stores parameters (shift, scale, and convolution
    kernel), performs the operation, and evaluates the likelihood.

    There are two modes for fitting----either chi^2 is calculated from
    the full covariance matrix (fit_with_covar=True), or chi^2 is
    calculated from just data errors (fit_with_covar=False).

    see do_map.py for examples of how to use.
    """

    def __init__(self,Lref,kernel='Hermite',fit_with_covar=False):
        """
        Constructs a rescaling model.  Needs a reference EmissionLine
        object, to which it will try to align data, a choice of
        functional form for the smoothing kernel, and if you want to
        use the covariance matrix during the fit.
        """
        #this is an emission line object, to which we scale to 
        self.Lref = Lref  

        self.use_covar = fit_with_covar
        #empty dictionary that will hold prior distributions.  keys
        #will be same as parameters, value will be a function that
        #evaluates the prior probability at the input parameter.
        self.prior_prob = {}
        self.kernelname = kernel

        if kernel == 'Delta':
            self._get_kernel = lambda x: sp.array([1.0])
            self.p = {'shift':1.0e-4, 'scale':1.0}
            self.set_scale = {'shift':0.05, 'scale':0.02}

        elif kernel == 'Gauss':
            self._get_kernel = self._Gauss

            #params are shift, scale, and width of gaussian
            #convolution kernel
            width_min = 0.51*(self.Lref.wv[1] - self.Lref.wv[0])
            self.p         = {'shift':1.0e-4, 'scale':1.00, 'width': width_min}
            self.set_scale = {'shift':0.05, 'scale':0.02, 'width':0.30}


        if kernel == 'Hermite':
            self._get_kernel = self._Hermite

            #params are shift, scale, width, h3, and h4 of
            #gauss-hermite polynomials
            width_min = 0.46*(self.Lref.wv[1] - self.Lref.wv[0])
            self.p         = {'shift':1.e-4, 'scale':1.00, 'width': width_min,
                              'h3':0.0, 'h4':0.0}
            self.set_scale = {'shift':0.05, 'scale':0.02, 'width':0.30,
                              'h3':0.03, 'h4':0.03}

    def __call__(self,L):
        """
        Overloaded the __call__ method so that you just use the model
        like a function to get the chi^2.  Input is an EmissionLine
        object, which will be matched to the reference.
        """

        if self.use_covar:
            y,var,mask,covar  = self._get_yz(L)
            lnlikely  = self._get_chi2_covar(y,covar,mask)
        else:
            y,var,mask  = self._get_yz(L,getcovar=False)
            lnlikely  = self._get_chi2(y,var,mask)

        lnlikely += self._add_priors()

        #take care of limited parameter space by setting prior
        #probability to 0 [ -ln(prob) = inf]
        lnlikely += self._prior_limits()

        return lnlikely


    def _get_chi2(self,y,v,m):
        return sp.sum(    (self.Lref.f[m] - y)**2/(self.Lref.ef[m]**2 + v))

    def _get_chi2_covar(self,y,C,m):
        vectoruse = sp.matrix(self.Lref.f[m] - y)
        Cuse = sp.matrix(C)
        return sp.ravel(vectoruse*linalg.inv(Cuse)*vectoruse.T)[0]


    def _add_priors(self):
        prior = 0
        for key in self.prior_prob.keys():
            prior += -2.*sp.log(
                self.prior_prob[key](self.p[key]) 
                )

        return prior


    def make_dist_prior(self,C,pname,burn = 0.5):
        params = sp.transpose(C.pchain)
        prior_dist = params[  C.index[pname]   ]
        icut = prior_dist.size*burn
        prior_dist = prior_dist[icut::]
        c1,m,c2 = sp.percentile(prior_dist,[16,50,84])
        print c1,m,c2

        #will model the distribution as a  gaussian, for now....
        self.prior_prob[pname] = lambda x: sp.exp(-0.5*(x - m)**2/ ( (c2-c1)/2 )**2 )
        self.p[pname] = m
        

    def make_func_prior(self,pname,func,params):
        self.prior_prob[pname] = lambda x: func(x,params) 


    def output(self,S,getcovar=True):
        """
        This will apply the rescaling model to a full spectrum.
        Default is to output the covariance matrix as well.
        """
        s = deepcopy(S)

        #shift
        s.wv -= self.p['shift']
        m = (S.wv >= s.wv.min()  )*(S.wv <= s.wv.max()  )
        y,z = s.interp(S.wv[m])
        
        #convolve
        k = self._get_kernel(S.wv[m])
        if getcovar:
            if self.kernelname == 'Delta':
                covar = get_covarmatrix(s.wv, S.wv[m], s.ef, k, 2)
            else:
                covar = get_covarmatrix(s.wv, S.wv[m], s.ef, k, 5*self.p['width'])

        z = sp.sqrt(sp.convolve(z**2,k**2,mode='same'))
        y = sp.convolve(y,k,mode='same')

        #scale
        z *= self.p['scale']
        y *= self.p['scale']
        if getcovar:
            covar *= self.p['scale']*self.p['scale']


        #edge effects left in for now
        sout = Spectrum()
        sout.wv = deepcopy(S.wv[m])
        sout.f  = y
        sout.ef = z

        if getcovar:
            return sout,m,covar
        else:
            return sout,m

    def _get_yz(self,L,getcovar=True):
        """
        Gets flux and error (y and z) near the line wavelengths, makes
        sure everything is aligned.
        """

        l = deepcopy(L)

        #shift
        l.wv -= self.p['shift']
        m = (self.Lref.wv >= l.wv.min() )*(self.Lref.wv <= l.wv.max() )
        y,z = l.interp(self.Lref.wv[m])
        #convolve
        k = self._get_kernel(self.Lref.wv[m])

        #have to make covar before smoothing z
        if getcovar:
            if self.kernelname == 'Delta':
                covar = get_covarmatrix(l.wv, self.Lref.wv[m], l.ef, k, 2)
            else:
                covar = get_covarmatrix(l.wv, self.Lref.wv[m], l.ef, k, 5*self.p['width'])

        z = sp.sqrt(sp.convolve(z**2,k**2,mode='same'))
        y = sp.convolve(y,k,mode='same')

        #scale
        z *= self.p['scale']
        y *= self.p['scale']
        if getcovar:
            covar *= self.p['scale']*self.p['scale']
        #add reference errors now to simplify the chi2----these don't
        #seem to matter much
            covar[sp.diag_indices_from(covar)] += self.Lref.ef[m]**2

        #trim 10% of data to help with edge effects and shifting the
        #data.  This number is hard-coded so that the degrees of
        #freedom are fixed during the fit.
        trim = round(0.05* (self.Lref.wv[m].size)) 


        z = z[trim:-trim]
        y = y[trim:-trim]
        if getcovar:
            covar = covar[:,trim:-trim]
            covar = covar[trim:-trim,:]

        #need a mask for reference when calculating chi^2
        m2 = (self.Lref.wv >= self.Lref.wv[m][trim] )*(self.Lref.wv < self.Lref.wv[m][-trim] )


        if getcovar:
            # Note that z**2 (error spectrum) is slightly different
            # than the diagonal of covar, because covariance was
            # ignored for z
            return y,z**2,m2,covar
        else:
            return y,z**2,m2

    def _Gauss(self,x):
        """
        Gaussian Smoothing kernel.
        """
        dlambda = x[1] - x[0]
        pixwidth = self.p['width']/dlambda
        prange = sp.r_[ -(x.size //2) + 1 : (x.size)//2  ]
        assert prange.size %2 == 1

        k = sp.exp(-0.5* prange**2/pixwidth**2)
        k /= abs(sp.sum(k))
        return k

    def _Hermite(self,x):
        """
        Gauss-Hermite Smoothing kernel.
        """
        dlambda = x[1] - x[0]
        pixwidth = self.p['width']/dlambda
        prange = sp.r_[ -(x.size //2) + 1 : (x.size)//2  ]
        
        h = H([ 1.0, 0.0, 0.0,self.p['h3'], self.p['h4'] ])
        #although the constants will divide out when normalizing the
        #kernel, they are important for making sure that h3 and h4 are
        #defined correctly.  Technically, this only matters for
        #choosing good intervals of h3 and h4, otherwise it is just a
        #mismatch of units

        #Equations are defined in van der Marel & Franx 1993
        k = 1./pixwidth/sp.sqrt(2*sp.pi)*sp.exp(-0.5*prange**2/pixwidth**2)*h(prange/pixwidth)
        k /= abs(sp.sum(k))


        return k


    def step(self):
        pout = {}
        for key in self.p.keys():
            pout[key] = self.p[key] + self.set_scale[key]*sp.randn()

        return pout

    def _prior_limits(self):
        prior = 0
        if len(self.p) > 2:
            dlambda = self.Lref.wv[1] - self.Lref.wv[0]
            #if width is too small, the kernel is undersampled.  Weird
            #things will happen, so this represents a lower limit.
            if self.p['width']/dlambda <0.5:
                prior = sp.inf

        if len(self.p) > 3:
            #experiments have found that h3 and h4 between -0.3 and
            #0.3 should be adequate (very diverse line shapes appear)
            if self.p['h3'] < -0.3:
                prior = sp.inf
            elif self.p['h3'] > 0.3:
                prior = sp.inf
            if self.p['h4'] < -0.3:
                prior = sp.inf
            elif self.p['h4'] > 0.3:
                prior = sp.inf

        return prior




class Chain(object):
    """
    This is an object for storing MCMC chains.  It names the
    parameters by storming them in a dictionary.  It knows how to read
    and write itself, and how to plot both histograms and triangle
    (correlation) plots.
    """
    def __init__(self):
        self.pchain   = []
        self.lnlikely = []

        self.index   = {}
        self.figure = None

#        self.figure,(self.axes) = plt.subplots(len(pnames) + 1,1)

    def add(self,M,chi2):
        if len(self.pchain) == 0:
            for i,k in enumerate(M.p.keys() ):            
                self.index[k] = i

            self.figure,(self.axes) = plt.subplots( len(M.p.keys()) + 1,1)

        self.pchain.append(deepcopy( M.p.values() ))
        self.lnlikely.append(chi2)

    def save(self,ofile):
        head = 'lnlikely   '
        outindex = []
        for key in self.index.keys():
            head += key+'   '
            outindex.append(self.index[key])
        sp.savetxt(ofile,sp.c_[self.lnlikely,sp.array(self.pchain)[:,outindex]],header=head)

    def read(self,ifile):
        fin = open(ifile,'r')
        line = fin.readline()
        pname = re.split('   ',line)
        if pname[0] != '# lnlikely':
            raise ValueError('Note a mapspec chain file! (must begin with lnlikely)')

        input_chain = sp.genfromtxt(ifile)
        self.lnlikely = input_chain[:,0]
        self.pchain   = input_chain[:,1::]
        for i,p in enumerate(pname[1:-1]):
            self.index[p] = i

        assert max(self.index.values()) == sp.transpose(self.pchain).shape[0] - 1


    def burn(self,frac):
        assert frac < 1
        cuti = int(frac*self.pchain.shape[0])
        self.pchain = self.pchain[cuti::]
        


    def plot(self,interact = 1):
        plotp = sp.transpose(self.pchain)
        if self.figure is None:
            self.figure,(self.axes) = plt.subplots( sp.transpose(self.pchain).shape[0] + 1,1)


        for ax in self.axes: ax.cla()

        self.axes[0].plot(self.lnlikely)
        self.axes[0].set_ylabel('ln likelihood')

        for key in self.index.keys():
            self.axes[self.index[key] + 1].plot(
                plotp[ self.index[key] ] 
                )
            self.axes[self.index[key] + 1].set_ylabel(key)

        for ax in self.axes[0:-1]:
            ax.set_xticks([])
        self.figure.subplots_adjust(hspace=0)
        if interact == 1:  
            plt.draw()
        return

    def plot_hist(self):
        plotp = sp.transpose(self.pchain)
        if self.figure is None:
            self.figure,(self.axes) = plt.subplots( sp.transpose(self.pchain).shape[0] + 1,1)
        for ax in self.axes: ax.cla()
        
        self.axes[0].hist(self.lnlikely,bins = 0.01*len(self.lnlikely))
        self.axes[0].set_xlabel('ln likelihood')
        for key in self.index.keys():
            self.axes[self.index[key] + 1].hist(
                plotp[ self.index[key] ] , bins = 0.01*len(plotp[self.index[key]])
                )
            self.axes[self.index[key] + 1].set_xlabel(key)

#        self.figure.set_size_inches(8,5)
        self.figure.tight_layout()

    def plot_corr(self):
        plotp = sp.transpose(self.pchain)
        if self.figure is None:
            self.gs1 = gridspec.GridSpec(plotp.shape[0],plotp.shape[0])

        for k1 in self.index.keys():
            for k2 in self.index.keys():
                if self.index[k1] > self.index[k2]: continue
                ax = plt.subplot(
                    self.gs1[
                        plotp.shape[0]-self.index[k1] - 1, plotp.shape[0]- self.index[k2] -1
                        ]
                    )

                if k1 == k2:
                    ax.hist(plotp[self.index[k1] ],0.01*len(plotp[ self.index[k1] ]),facecolor='k',alpha=0.5)
                else:
                    ax.plot(plotp[self.index[k2]],plotp[self.index[k1]],'ko',ms=2,rasterized=True,alpha=0.15)

                if self.index[k2] == plotp.shape[0] - 1:
                    ax.set_ylabel(k1)
                    if self.index[k1] != 0:
                        ax.set_xticklabels([])
                        ax.tick_params(labelright=True)
                        ax.set_yticklabels([])
                    else:
                        ax.set_xlabel(k2)

                elif self.index[k1] == 0:
                    ax.set_xlabel(k2)
                    if self.index[k2] == 0:
                        ax.yaxis.tick_right()
                    else:
                        ax.set_yticklabels([])


                elif self.index[k1] == self.index[k2]:
                    ax.yaxis.tick_right()
                    if self.index[k1] != plotp.shape[0] - 1:
                        ax.set_xticklabels([])



                else:
                    ax.set_xticklabels([])
                    ax.set_yticklabels([])



        plt.gcf().subplots_adjust(hspace=0,wspace=0)




def get_cc(y1,y2,x1,x2):
    """
    Easy way of estimating the shift to the nearest pixel (given in
    wavelength units).

    y1 = flux of spec1
    y2 = flux of spec2
    x1 = wavelengths of spec1
    x2 = wavelengths of spec2
    """

    if x1.size > x2.size:
        m = (x1 > x2.min())*(x1 < x2.max())
        yuse = [y1[m],y2]
    else:
        m = (x2 > x1.min())*(x2 < x1.max())
        yuse = [y1,y2[m]]


    cc = sp.correlate(yuse[0],yuse[1],mode='same')
    i  = sp.where(cc == cc.max())[0]
    shift = (x1[1] - x1[0] )*(cc.size//2 - i)
    return shift

def get_covarmatrix(x,xinterp,z,k,breakwidth):
    """
    Calculates the covariance matrix when needed.  Assumes both an
    interpolation and a smoothing----for now, only linear
    interpolation will work (only does one diagonal, but propagates
    the error correctly).
    """

    isort = sp.searchsorted(x,xinterp)
    f = (xinterp - x[isort -1 ])/(x[isort] - x[isort -1])
    z2 = sp.sqrt(
        (f**2)*(z[isort]**2) + ((1 - f)**2)*(z[isort - 1]**2)
        )
    #for a delta function
    if k.size == 1:
        return sp.diag(z2**2)

    covar1 = sp.zeros((z2.size ,z2.size ))
    covar2 = sp.zeros((z2.size ,z2.size ))

    #the part from interpolation---searchsorted has thrown out the
    #first index, the last index won't be selected because of the slice
    covar1[sp.diag_indices_from(covar1)] = z2**2
#    print sp.shape(f), sp.shape(z[isort.min():isort.max()-1]),sp.shape(z)
    diag1 = f[0:-1]*(1-f[0:-1])*(z[isort.min()  : isort.max() ]**2)

    #linear interpolation only has one diagonal
    covar1 += sp.diag(diag1,1)
    covar1 += sp.diag(diag1,-1)
    covar1 = sp.matrix(covar1)
                
    #the part from convolution
    #make kernel match size of input
    if k.size == z2.size  - 2:
        k = sp.r_[0,k,0]
    elif k.size == z2.size -1:
        k = sp.r_[0,k]
    #force it to wrap around
    cent = k.size//2
    k = sp.r_[ k[cent::], k[0:cent ] ]

    #for matrix equation, see Gardner 2003, Uncertainties in
    #Interpolated Spectral Data; equation 6

    # seems like there is a better way than a double loop....
    for i in range(z2.size):
        for n in range(int(breakwidth)):
            #can shorten the loop because most of the matrix is
            #zero:the idea is that kernels that are far apart
            #should have zero overlap.  If k2 gets shifted
            #relative to k1 more than 5x the kernel width, assume
            #no overlap
            j = i + n
            if j > z2.size - 1: j = z2.size -1
            k1 = sp.matrix(sp.roll(k,i))
            k2 = sp.matrix(sp.roll(k,j))
            trim1 = cent + i
            if trim1 <= k1.size:
                k1[:,trim1::] = 0
            else:
                k1[:,0: trim1 - k1.size] = 0

            trim2 = cent + j
            if trim2 <= k2.size:
                k2[:,trim2::] = 0
            else:
                k2[:,0: (trim2 - k2.size)] = 0

            covar2[i,j] = k1*covar1*k2.T
        #matrix is symmetric
    covar2 += covar2.T
    covar2[sp.diag_indices_from(covar2)] /= 2.
   
    return covar2


def metro_hast(ntrial,D,M,plot=False,keep=False):
    """
    This actualy does the work to fit the model to the data.  

    ntrial = number of iterations in the MCMC
    M = RescaleModel object (defined with the reference and smoothing kernel)
    D = Data (EmissionLine Object)

    plot=True will turn on interactive plotting---you can watch the
    chains as they progress!

    keep=True will return the Chain object used to store the MCMC,
    which can be saved latter (see do_map.py).
    

    """
    Mtry= deepcopy(M)
    chi2 = 1.e12
    chi2best = 1.e12

    pbest = deepcopy(M.p)
    accept = 0

    c = Chain()
    c.add(M,M(D))
    if plot ==1:
        plt.ion()
        c.plot()

    for i in range(ntrial):
        Mtry.p = M.step()
        chi2try = Mtry(D)
        
        if chi2try < chi2:
            
            M.p = deepcopy(Mtry.p)
            chi2 = deepcopy(chi2try)

            accept += 1
            c.add(M,chi2)
                
            if chi2 < chi2best:
                chi2best = deepcopy(chi2)
                pbest = deepcopy(M.p)

        else:
            prob = sp.exp(-chi2try/chi2)
            r = sp.rand()
            if r <= prob:
                M.p = deepcopy(Mtry.p)
                chi2 = deepcopy(chi2try)
                accept += 1
            c.add(M,chi2)
                
        if i%500 == 0 :
            print i,chi2best,chi2try
            if plot ==1:
                c.plot()

    if keep == 1:
        return chi2best,pbest,accept/float(ntrial),c
    else:
        return chi2best,pbest,accept/float(ntrial)



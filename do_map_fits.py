import matplotlib
matplotlib.use('TkAgg') 

import scipy as sp
import matplotlib.pyplot as plt
from spectrum import *
from mapspec import *
from copy import deepcopy

import sys,os,time

from astropy.io import fits

def savefits(ofile,spec,head):
    data = sp.array([
            [spec.f],
            [spec.ef]
            ])
    
    #assume grid spacing and first pix has not changed
    head['CRVAL1'] = spec.wv[0]
    head['COMMENT'] = 'Modified by mapspec on %s'%(time.strftime("%c"))

    fits.writeto(ofile,data,header=head,clobber=True)

#How to interpolate?  Note that only linear interpolation does the
#errors properly, for now
istyle = sys.argv[3]

#What spectrum to use as a reference?
sref   = TextSpec(sys.argv[1],style=istyle)

#file with window for alignment, i.e., [OIII]lambda 5007.  Format is:
#line 1:  wavelength_of_line_low, wavelength_of_line_high
#line 2:  continuum window 1 (low, high)
#line 3: continuum window 2(low, high)
#see run_map.sh for more
window = sp.genfromtxt(sys.argv[2])

#pops out the line from the reference spectrum
lref   = EmissionLine(sref,window[0],[ window[1],window[2] ] )

#list of spectra to align
speclist = sp.genfromtxt(sys.argv[4],dtype=str)

#output file of parameters
fout = open(sys.argv[5],'a')

#write covariances?
if sys.argv[6] == 'covar':
    get_covar = True
    if os.path.isdir('covar_matrices') == False:
        os.system('mkdir covar_matrices')
else:
    get_covar = False

if sys.argv[7] == 'chains':
    get_chains = True
    if os.path.isdir('chains') == False:
        os.system('mkdir chains')
    else:
        get_chains = False

#plt.ion()
for spec in speclist:
    print spec
    s = FitsSpec(spec,style=istyle)

    s0 = get_cc(sref.f,s.f,sref.wv,s.wv)
    s.wv -= s0[0]

    l = EmissionLine(s,window[0],[ window[1],window[2] ])
    l.set_interp(style=istyle)

    f   = RescaleModel(lref,kernel="Delta")
    try: 
        chi2_delta,p_delta,frac_delta = metro_hast(1000,l,f,keep=False)
        print frac_delta
    except:
        chi2_delta,p_delta,frac_delta = 999,{'shift':-99, 'scale':-99}, 0 
     

    f    = RescaleModel(lref,kernel="Gauss")
 
    try: 
#       keep = True returns the chain, which can be saved and used latter for getting model errors (mode_rescale.py).
        chi2_gauss,p_gauss,frac_gauss,chain_gauss = metro_hast(5000,l,f,keep=True)
#       Try this code to watch the chain as it progresses
#        plt.ion()
#        chi2_gauss,p_gauss,frac_gauss,chain_gauss = metro_hast(5000,l,f,keep=True,plot=True)
        print frac_gauss
    except:
        chi2_gauss,p_gauss,frac_gauss = 999,{'shift':-99, 'scale':-99, 'width':-99}, 0 
        
    if chi2_delta < chi2_gauss:
        f.p = {'shift':p_delta['shift'], 'scale':p_delta['scale'], 'width': 0.001 }
    else:
        f.p = p_gauss

    sout,dummy,covar = f.output(s)

    hout = fits.getheader(spec)
    savefits('scale_'+spec,sout,hout)

    if get_covar:
        sp.savetxt('covar_matrices/covar_'+spec,covar)
    if get_chains:
        chain_gauss.save('chains/'+spec+'.chain.gauss')

    
    f    = RescaleModel(lref,kernel="Hermite")
#    Here is an example of how to put in a prior----we are using the
#    posterior distribution of the kernel width from the pure Gaussian
#    as a prior on the width for the Gauss-Hermite kernel.
#    'burn=0.75' means we throw out the first 3/4 of the chain
#    (assumed to be burn in).

#    f.make_dist_prior(chain_gauss,'width', burn=0.75)

#    Or, you can specify an analytic function, if say, you have a
#    guess of what the width should be----here, the prior is a
#    Gaussian of mean 1.8 angstroms and std 1.0 angstroms.

#    def wprior(x,params):
#        return sp.exmp(-0.5*(x - params[0])**2/ (params[1])**2 )
#    f.make_func_prior('width', wprior, [1.8, 1.0] )

    try:
        chi2_herm,p_herm,frac_herm,chain_herm = metro_hast(50000,l,f,keep=True)
        print frac_herm
    except:
        chi2_herm,p_herm,frac_herm = 999, {'shift':99,'scale':-99,'width':-99,'h3':-99,'h4':-99}, 0 

    if chi2_delta < chi2_herm:
        f.p = {'shift':p_delta['shift'], 'scale':p_delta['scale'], 'width': 0.001 , 'h3':0.0, 'h4':0.0}
    else:
        f.p = p_herm

    sout,dummy,covar = f.output(s)

    fout.write(
        "%15s % 8.4f  %10.2f % 8.4f % 8.4f % 5.2f %10.2f % 8.4f % 8.4f % 8.4f % 5.2f % 10.2f % 8.4f % 8.4f % 8.4f % 5.4e % 5.4e %8.4f\n"%
        (spec,s0[0],
         chi2_delta,p_delta['shift'],p_delta['scale'], frac_delta,
         chi2_gauss,p_gauss['shift'],p_gauss['scale'],p_gauss['width'],frac_gauss,
         chi2_herm,p_herm['shift'],p_herm['scale'],p_herm['width'],p_herm['h3'],p_herm['h4'],frac_herm)
        )
    fout.flush()

    hout = fits.getheader(spec)
    savefits('scale.h._'+spec,sout,hout)

    if get_covar:
        sp.savetxt('covar_matrices/covar.h._'+spec,covar)
    if get_chains:
        chain_herm.save('chains/'+spec+'.chain.herm')


        
    plt.close('all')
fout.close()

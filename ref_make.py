import scipy as sp
from scipy.signal import correlate
import matplotlib.pyplot as plt
from spectrum import Spectrum,EmissionLine,TextSpec
from copy import deepcopy
import sys

"""
This will combine a list of spectra using a weighted average.

The program runs an MCMC to calculate the shift that best aligns the
spectra, in order to use a consistent wavelength grid.  The fit uses
some target emission line.

'Best fit' is not rigorously defined, because different shifts cause
different overlaps of pixels, so the degrees of freedom are changing.
Nevertheless, it is a pretty robust algorithm and seems to be good
enough for most purposes.

input is a list of spectra 'speclist' that are combined with a
weighted average.  The shifts are solved to align with the FIRST
spectrum in this list.

The user must enter a file designating the window from which to
extract the emission line.  This follows the usual format, i.e., 3
lines specifying:

line_blue_edge     line_red_edge
bluecont_blue_edge bluecont_red_edge
redcont_blue_edge  redcont_red_edge

"""


def get_chi2(s1,s2,shift):
    trim = int(abs(shift/(s1.wv[1] - s1.wv[0]))) + 1
#    print trim, s2.wv.size,shift
    if trim == 0: trim = 1
    xnew = s2.wv[trim : -trim] - shift
    #resample the reference at the new wavelength grid
    y1,z1 = s1.interp(xnew)

    return sp.sum( 
        (y1 - s2.f[trim: - trim])**2/(z1**2 + s2.ef[trim: - trim]**2)
        )

def get_cc(y1,y2,x):
    cc = correlate(y1,y2,mode='same')
    i  = sp.where(cc == cc.max())[0]
    shift = (x[1] - x[0] )*(cc.size//2 - i)

    return shift

def tidy(xout,yout,zout):
    xmin = xout[0]
    for x in xout:
        if x.size < xmin.size:
            xmin = deepcopy(x)

    print xmin
    for i in range(sp.shape(xout)[0]):
        j = sp.in1d(xout[i],xmin)

        yout[i] = yout[i][j]
        zout[i] = zout[i][j]

    print sp.shape(xout),sp.shape(yout),sp.shape(zout)
    print yout
    yout  = sp.array(yout)
    zout = sp.array(zout)
    ymean = sp.sum( yout/zout**2,axis = 0 )/sp.sum(1./zout**2, axis = 0)
    error = sp.sqrt( 
        1./sp.sum(1./zout**2,axis = 0) 
        )

    return xmin,ymean,error


def HM(ntrial,s1,s2,p):

    chi2 = get_chi2(s1,s2,p)
    chi2best = 1.e12

    pbest = deepcopy(p)

    accept = 0

    for i in range(ntrial):

        ptry = p + sp.randn()*0.1
 
        chi2try = get_chi2(s1,s2,ptry)

        if i%10 == 0 :
            print i,chi2best,chi2,chi2try

        if chi2try < chi2:
            
            p = deepcopy(ptry)
            chi2 = deepcopy(chi2try)

            accept += 1
            if chi2 < chi2best:
                pbest = deepcopy(ptry)
                chi2best = deepcopy(chi2try)


        else:
            prob = sp.exp(-chi2try/chi2)
            r = sp.rand()
            if r <= prob:
                p = deepcopy(ptry)
                chi2 = deepcopy(chi2try)
                accept += 1

    return chi2best,pbest,accept/float(ntrial)

if len(sys.argv) == 1:
    print 'Usage:'
    print 'python ref_make.py   speclist    window  outfile.txt'
    print 'speclist--      1 col ascii file with list of files to combine'
    print 'window---       window file designating wavelengths for the EmissionLine'
    print 'outfile.txt---  output spectrum, after smoothing'
    exit

#list of spectra for the reference
reflist = sp.genfromtxt(sys.argv[1],dtype='a')
#window for line to align
window = sp.genfromtxt(sys.argv[2])


S,L = [],[]
for ref in reflist:
    s = TextSpec(ref)
    s.set_interp(style='linear')
    m= (s.wv > 4500)*(s.wv <7500)
    s.wv = s.wv[m]
    s.f  = s.f[m]
    s.ef = s.ef[m]


    S.append(s)

#    plt.plot(s.wv,s.f,'k')
#    plt.show()
#trimmax = 0

xout = []
yout = []
zout = []

shiftout = []


lref = EmissionLine(S[0],window[0],[window[1],window[2]])
print lref.style

for s in S[1::]:
    
    shift0 = get_cc(S[0].f,s.f,S[0].wv)
    print 'shift0',shift0
    shift0 = 0
    l = EmissionLine(s,window[0],[window[1],window[2]])
#    print l.ef[0:5]
#    raw_input()
#    plt.plot(l.wv,l.f,'k')
#    plt.plot(lref.wv,lref.f,'r')
#    plt.show()
    chi,shiftuse,frac = HM(1000,lref,l,shift0)

    print 'chi2,shiftuse,frac'
    print chi,shiftuse,frac

    shiftout.append(shiftuse)
    s.wv -= shiftuse

    trim = int(abs(shiftuse/(s.wv[1] - s.wv[0]))) + 1
#    if trim > trimmax: trimmax = trim
#    print 'trim',trimmax
    
    y1,z1 = s.interp(S[0].wv[trim:-trim])

    plt.plot(S[0].wv[trim:-trim],y1,'k')
    plt.plot(S[0].wv[trim:-trim],z1,'r')
    plt.show()

    xout.append(S[0].wv[trim:-trim])
    yout.append(y1)
    zout.append(z1)


xout.append(S[0].wv)
yout.append(S[0].f)
zout.append(S[0].ef)

xref,yref,zref = tidy(xout,yout,zout)


sp.savetxt(sys.argv[3],sp.c_[xref,yref,zref])
sp.savetxt('ref_shifts.dat',sp.c_[shiftout])

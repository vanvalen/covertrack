"""
Image alignment based on mutual information. 
Some functions are adapted/modified from cellprofiler. 

>r1, r2 = block_mi_align_multi_hypothesis(img1, img2)
>cimg1, cimg2 = crop_images_based_on_r1_r2(img1, img2, r1, r2)
cimg1 and cimg2 are the aligned and cropped images.
"""

import scipy.ndimage as scind
import numpy as np
import scipy
from centrosome.filter import stretch
from skimage.measure import block_reduce
from scipy.ndimage.filters import gaussian_laplace
from skimage.exposure import equalize_hist


class BaseMutualInfoAligner(object):
    def __init__(self, img1, img2, mask0=None, DOWNSAMPLE=(16, 8, 4, 2)):
        self.img1, self.img2 = img1, img2
        if mask0 is None:
            mask0 = np.ones(img1.shape, bool)
        self.mask0 = mask0
        self.DOWNSAMPLE = DOWNSAMPLE

    def execute(self):
        self.preprocessing()
        self.initial_mi()
        self.mi_loop()
        self.mi_last()

    def preprocessing(self):
        self.img1, self.img2 = equalize_hist(self.img1), equalize_hist(self.img2)

    def initial_mi(self):
        dimg1, dimg2, dmask = self.downsampling(self.DOWNSAMPLE[0])
        arr, i_list, j_list = self.search_all_mi(dimg1, dimg2, dmask, dmask)
        self.ini_j, self.ini_i = self.pick_coords(arr, i_list, j_list)
 
    def downsampling(self, factor):
        # [1:-1, 1:-1] added in case a image has odd shape.
        dimg1 = block_reduce(self.img1, (factor, factor))[1:-1, 1:-1]
        dimg2 = block_reduce(self.img2, (factor, factor))[1:-1, 1:-1]
        dmask = block_reduce(self.mask0, (factor, factor))[1:-1, 1:-1]
        dmask = dmask!=0
        return dimg1, dimg2, dmask

    def search_all_mi(self, pp1, pp2, mask1, mask2):
        best = 0
        i_list = range(-pp1.shape[0], pp1.shape[0])
        j_list = range(-pp1.shape[1], pp1.shape[1])
        arr = np.zeros((len(i_list), len(j_list)))
        for n1, new_i in enumerate(i_list):
            for n2, new_j in enumerate(j_list):
                p2, p1 = offset_slice(pp2, pp1, new_i, new_j)
                m2, m1 = offset_slice(mask2, mask1, new_i, new_j)
                if p2.any() and p1.any() and m1.any() and m2.any():
                    info = mutualinf(p1, p2, m1, m2)
                    arr[n1, n2] = info
        self.arr, self.i_list, self.j_list = arr, i_list, j_list
        return arr, i_list, j_list

    def pick_coords(self, arr, i_list, j_list):
        a1, a2 = np.where(arr == arr.max())
        return j_list[a2], i_list[a1]

    def mi_loop(self):
        pass
    
    def mi_last(self):
        pass


class BaseMutualInfoAlignerLog(BaseMutualInfoAligner):

    def search_all_mi(self, pp1, pp2, mask1, mask2):
        CUT = 10
        best = 0
        i_list = range(-pp1.shape[0]+CUT, pp1.shape[0]-CUT)
        j_list = range(-pp1.shape[1]+CUT, pp1.shape[1]-CUT)
        arr = np.zeros((len(i_list), len(j_list)))
        for n1, new_i in enumerate(i_list):
            for n2, new_j in enumerate(j_list):
                p2, p1 = offset_slice(pp2, pp1, new_i, new_j)
                m2, m1 = offset_slice(mask2, mask1, new_i, new_j)
                if p2.any() and p1.any() and m1.any() and m2.any():
                    info = mutualinf(p1, p2, m1, m2)
                    arr[n1, n2] = info
        self.arr, self.i_list, self.j_list = arr, i_list, j_list
        return arr, i_list, j_list

    def pick_coords(self, arr, i_list, j_list):
        self.gl = gaussian_laplace(arr, 1)
        a1, a2 = np.where(self.gl==self.gl.min())
        return j_list[a2], i_list[a1]    


class MutualInfoAlignerLogLoop(BaseMutualInfoAlignerLog):
    def mi_loop(self):
        tj, ti = self.ini_j, self.ini_i
        for num, di in enumerate(self.DOWNSAMPLE[1:]):
            dimg1, dimg2, dmask = self.downsampling(di)
            tj, ti = tj*int(self.DOWNSAMPLE[num]/di), ti*int(self.DOWNSAMPLE[num]/di)
            best = mutualinf(dimg1, dimg2, dmask, dmask)
            tj, ti, _ = self.optimize_max_mi_from_offset(dimg1, dimg2, dmask, dmask, ti, tj, best)
        self._j, self._i = tj, ti

    def mi_last(self):
        tj, ti = self._j * self.DOWNSAMPLE[-1], self._i * self.DOWNSAMPLE[-1]
        best = mutualinf(self.img1, self.img2, self.mask0, self.mask0)
        tj, ti, mi = self.optimize_max_mi_from_offset(self.img1, self.img2, self.mask0, self.mask0, ti, tj, best)
        self._j, self._i, self.mi = tj, ti, mi

    def optimize_max_mi_from_offset(self, pixels1, pixels2, mask1, mask2, i, j, best):
        while True:
            last_i = i
            last_j = j
            for new_i in range(last_i - 1, last_i + 2):
                for new_j in range(last_j - 1, last_j + 2):
                    if new_i == 0 and new_j == 0:
                        continue
                    p2, p1 = offset_slice(pixels2, pixels1, new_i, new_j)
                    m2, m1 = offset_slice(mask2, mask1, new_i, new_j)
                    if p1[m1].any() and p2[m2].any():
                        info = mutualinf(p1, p2, m1, m2)
                    else:
                        info = 0
                    if info > best:
                        best = info
                        i = new_i
                        j = new_j
            if i == last_i and j == last_j:
                return j, i, best


class MutualInfoAlignerMultiHypothesis(MutualInfoAlignerLogLoop):
    """
    Calculate all the possible MI in the downsampled image and then
    search local MI in a less downsampled image based.
    """
    def execute(self):
        self.preprocessing()
        self.initial_mi()
        self.ini_j_all = self.ini_j[:]
        self.ini_i_all = self.ini_i[:]
        store, mistore = [], []
        for self.ini_j, self.ini_i in zip(self.ini_j_all, self.ini_i_all):
            self.mi_loop()
            self.mi_last()
            store.append((self._j, self._i))
            mistore.append(self.mi)
        j, i = store[mistore.index(max(mistore))]
        self.store = store
        self.mistore = mistore
        self._j, self._i, self.mi = j, i, max(mistore)

    def pick_coords(self, arr, i_list, j_list):        
        HYPNUM = 5
        gl = gaussian_laplace(arr, 1)
        # Divide images into 25 blocks and calculate minimum
        BLK = 5
        hbl, wbl = np.linspace(0, gl.shape[0], BLK, dtype=int), np.linspace(0, gl.shape[1], BLK, dtype=int)
        gl_min = []
        for (h1, h2) in zip(hbl[:-1], hbl[1:]):
            for (w1, w2) in zip(wbl[:-1], wbl[1:]):
                gl_min.append(gl[h1:h2, w1:w2].min())
        gl_min.sort()
        ji_list = []
        # plt.imshow(arr)
        # Pick top HYPNUM minimum from 25 blocks.
        j_all, i_all = [], []
        for ii in range(HYPNUM):
            a1, a2 = np.where(gl==gl_min[ii])
            j_all.append(j_list[a2])
            i_all.append(i_list[a1])
        return j_all, i_all


def mutualinf(x, y, maskx, masky):
    x = x[maskx & masky]
    y = y[maskx & masky]
    return entropy(x) + entropy(y) - entropy2(x, y)


def crop_images_based_on_r1_r2(img1, img2, r1, r2):
    if r2<0 and r1<0:
        cimg1, cimg2 = img1[:r2, :r1], img2[-r2:, -r1:]
    elif r2<0 and r1>0:
        cimg1, cimg2 = img1[:r2, r1:], img2[-r2:, :-r1]
    elif r2>0 and r1<0:
        cimg1, cimg2 = img1[r2:, :r1], img2[:-r2, -r1:]
    elif r2>0 and r1>0:
        cimg1, cimg2 = img1[r2:, r1:], img2[:-r2, :-r1]
    return cimg1, cimg2


def mask_image_edge(img, wpix, hpix):
    mask = np.ones(img.shape, bool)
    mask[hpix:-hpix, wpix:-wpix] = False
    return mask


def align_mutual_information(pixels1, pixels2, mask1, mask2):
    '''Align the second image with the first using mutual information
    returns the x,y offsets to add to image1's indexes to align it with
    image2
    The algorithm computes the mutual information content of the two
    images, offset by one in each direction (including diagonal) and
    then picks the direction in which there is the most mutual information.
    From there, it tries all offsets again and so on until it reaches
    a local maximum.
    '''
    #
    # TODO: Possibly use all 3 dimensions for color some day
    #
    if pixels1.ndim == 3:
        pixels1 = np.mean(pixels1, 2)
    if pixels2.ndim == 3:
        pixels2 = np.mean(pixels2, 2)

    def mutualinf(x, y, maskx, masky):
        x = x[maskx & masky]
        y = y[maskx & masky]
        return entropy(x) + entropy(y) - entropy2(x, y)

    maxshape = np.maximum(pixels1.shape, pixels2.shape)
    pixels1 = reshape_image(pixels1, maxshape)
    pixels2 = reshape_image(pixels2, maxshape)
    mask1 = reshape_image(mask1, maxshape)
    mask2 = reshape_image(mask2, maxshape)

    best = mutualinf(pixels1, pixels2, mask1, mask2)
    i = 0
    j = 0
    while True:
        last_i = i
        last_j = j
        for new_i in range(last_i - 1, last_i + 2):
            for new_j in range(last_j - 1, last_j + 2):
                if new_i == 0 and new_j == 0:
                    continue
                p2, p1 = offset_slice(pixels2, pixels1, new_i, new_j)
                m2, m1 = offset_slice(mask2, mask1, new_i, new_j)
                info = mutualinf(p1, p2, m1, m2)
                if info > best:
                    best = info
                    i = new_i
                    j = new_j
        if i == last_i and j == last_j:
            return j, i



def offset_slice(pixels1, pixels2, i, j):
    '''Return two sliced arrays where the first slice is offset by i,j
    relative to the second slice.
    '''
    if i < 0:
        height = min(pixels1.shape[0] + i, pixels2.shape[0])
        p1_imin = -i
        p2_imin = 0
    else:
        height = min(pixels1.shape[0], pixels2.shape[0] - i)
        p1_imin = 0
        p2_imin = i
    p1_imax = p1_imin + height
    p2_imax = p2_imin + height
    if j < 0:
        width = min(pixels1.shape[1] + j, pixels2.shape[1])
        p1_jmin = -j
        p2_jmin = 0
    else:
        width = min(pixels1.shape[1], pixels2.shape[1] - j)
        p1_jmin = 0
        p2_jmin = j
    p1_jmax = p1_jmin + width
    p2_jmax = p2_jmin + width

    p1 = pixels1[p1_imin:p1_imax, p1_jmin:p1_jmax]
    p2 = pixels2[p2_imin:p2_imax, p2_jmin:p2_jmax]
    return p1, p2


def entropy(x):
    '''The entropy of x as if x is a probability distribution'''
    histogram = scind.histogram(x.astype(float), np.min(x), np.max(x), 256)
    n = np.sum(histogram)
    if n > 0 and np.max(histogram) > 0:
        histogram = histogram[histogram != 0]
        return np.log2(n) - np.sum(histogram * np.log2(histogram)) / n
    else:
        return 0


def entropy2(x, y):
    '''Joint entropy of paired samples X and Y'''
    #
    # Bin each image into 256 gray levels
    #
    x = (stretch(x) * 255).astype(int)
    y = (stretch(y) * 255).astype(int)
    #
    # create an image where each pixel with the same X & Y gets
    # the same value
    #
    xy = 256 * x + y
    xy = xy.flatten()
    sparse = scipy.sparse.coo_matrix((np.ones(xy.shape),
                                      (xy, np.zeros(xy.shape))))
    histogram = sparse.toarray()
    n = np.sum(histogram)
    if n > 0 and np.max(histogram) > 0:
        histogram = histogram[histogram > 0]
        return np.log2(n) - np.sum(histogram * np.log2(histogram)) / n
    else:
        return 0


def reshape_image(source, new_shape):
    '''Reshape an image to a larger shape, padding with zeros'''
    if tuple(source.shape) == tuple(new_shape):
        return source

    result = np.zeros(new_shape, source.dtype)
    result[:source.shape[0], :source.shape[1]] = source
    return result





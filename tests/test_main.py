import numpy as np
import pytest
from main import median_stack, find_images


def test_median():
    a = np.array([[0.2, np.nan]])
    b = np.array([[0.6, 0.8]])
    result = median_stack([a, b])
    assert np.allclose(result, [[0.4, 0.8]])


def test_empty_folder(tmp_path):
    with pytest.raises(ValueError, match='No tif images'):
        find_images(tmp_path, 'tif')


def test_bad_date(tmp_path):
    (tmp_path / 'bad_name.tif').touch()
    with pytest.raises(ValueError, match='YYYYMM or YYYYMMDD'):
        find_images(tmp_path, 'tif')


def test_monthly_filename(tmp_path):
    (tmp_path / 'S2_202206.tif').touch()
    dates = find_images(tmp_path, 'tif')
    assert dates[0][0].strftime('%Y-%m') == '2022-06'

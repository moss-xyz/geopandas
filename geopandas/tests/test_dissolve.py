import warnings

import numpy as np
import pandas as pd

from shapely import MultiPolygon, Polygon

import geopandas
from geopandas import GeoDataFrame, read_file
from geopandas._compat import GEOS_GE_312, HAS_PYPROJ, PANDAS_GE_30, SHAPELY_GE_21

import pytest
from geopandas.testing import assert_geodataframe_equal, geom_almost_equals
from pandas.testing import assert_frame_equal


@pytest.fixture
def nybb_polydf(nybb_filename):
    nybb_polydf = read_file(nybb_filename)
    nybb_polydf = nybb_polydf[["geometry", "BoroName", "BoroCode"]]
    nybb_polydf = nybb_polydf.rename(columns={"geometry": "myshapes"})
    nybb_polydf = nybb_polydf.set_geometry("myshapes")
    nybb_polydf["manhattan_bronx"] = 5
    nybb_polydf.loc[3:4, "manhattan_bronx"] = 6
    nybb_polydf["BoroCode"] = nybb_polydf["BoroCode"].astype("int64")
    return nybb_polydf


@pytest.fixture
def merged_shapes(nybb_polydf):
    # Merged geometry
    manhattan_bronx = nybb_polydf.loc[3:4]
    others = nybb_polydf.loc[0:2]

    collapsed = [others.geometry.union_all(), manhattan_bronx.geometry.union_all()]
    merged_shapes = GeoDataFrame(
        {"myshapes": collapsed},
        geometry="myshapes",
        index=pd.Index([5, 6], name="manhattan_bronx"),
        crs=nybb_polydf.crs,
    )

    return merged_shapes


@pytest.fixture
def first(merged_shapes):
    first = merged_shapes.copy()
    first["BoroName"] = ["Staten Island", "Manhattan"]
    first["BoroCode"] = [5, 1]
    return first


@pytest.fixture
def expected_mean(merged_shapes):
    test_mean = merged_shapes.copy()
    test_mean["BoroCode"] = [4, 1.5]
    return test_mean


def test_geom_dissolve(nybb_polydf, first):
    test = nybb_polydf.dissolve("manhattan_bronx")
    assert test.geometry.name == "myshapes"
    assert geom_almost_equals(test, first)


@pytest.mark.skipif(not HAS_PYPROJ, reason="pyproj not installed")
def test_dissolve_retains_existing_crs(nybb_polydf):
    assert nybb_polydf.crs is not None
    test = nybb_polydf.dissolve("manhattan_bronx")
    assert test.crs is not None


def test_dissolve_retains_nonexisting_crs(nybb_polydf):
    nybb_polydf.geometry.array.crs = None
    test = nybb_polydf.dissolve("manhattan_bronx")
    assert test.crs is None


def test_first_dissolve(nybb_polydf, first):
    test = nybb_polydf.dissolve("manhattan_bronx")
    assert_frame_equal(first, test, check_column_type=False)


def test_mean_dissolve(nybb_polydf, first, expected_mean):
    test = nybb_polydf.dissolve("manhattan_bronx", aggfunc="mean", numeric_only=True)
    # for non pandas "mean", numeric only cannot be applied. Drop columns manually
    test2 = nybb_polydf.drop(columns=["BoroName"]).dissolve(
        "manhattan_bronx", aggfunc="mean"
    )

    assert_frame_equal(expected_mean, test, check_column_type=False)
    assert_frame_equal(expected_mean, test2, check_column_type=False)


def test_dissolve_emits_other_warnings(nybb_polydf):
    # we only do something special for pandas 1.5.x, but expect this
    # test to be true on any version
    def sum_and_warn(group):
        warnings.warn("foo")  # noqa: B028
        return group.sum(numeric_only=False)

    with pytest.warns(UserWarning, match="foo"):
        nybb_polydf.dissolve("manhattan_bronx", aggfunc=sum_and_warn)


def test_multicolumn_dissolve(nybb_polydf, first):
    multi = nybb_polydf.copy()
    multi["dup_col"] = multi.manhattan_bronx
    multi_test = multi.dissolve(["manhattan_bronx", "dup_col"], aggfunc="first")

    first_copy = first.copy()
    first_copy["dup_col"] = first_copy.index
    first_copy = first_copy.set_index([first_copy.index, "dup_col"])

    assert_frame_equal(multi_test, first_copy, check_column_type=False)


def test_reset_index(nybb_polydf, first):
    test = nybb_polydf.dissolve("manhattan_bronx", as_index=False)
    comparison = first.reset_index()
    assert_frame_equal(comparison, test, check_column_type=False)


@pytest.mark.parametrize(
    "grid_size, expected",
    [
        (
            None,
            MultiPolygon(
                [
                    Polygon([(0, 0), (10, 0), (10, 9)]),
                    Polygon([(0, 0.4), (4.6, 5), (0, 5)]),
                ]
            ),
        ),
        (1, Polygon([(0, 5), (5, 5), (10, 9), (10, 0), (0, 0)])),
    ],
)
def test_dissolve_grid_size(grid_size, expected):
    gdf = geopandas.GeoDataFrame(
        geometry=[
            Polygon([(0, 0), (10, 0), (10, 9)]),
            Polygon([(0, 0.4), (4.6, 5), (0, 5)]),
        ]
    )

    dissolved_gdf = gdf.dissolve(grid_size=grid_size)
    assert dissolved_gdf.geometry[0].equals(expected)


def test_dissolve_none(nybb_polydf):
    test = nybb_polydf.dissolve(by=None)
    expected = GeoDataFrame(
        {
            nybb_polydf.geometry.name: [nybb_polydf.geometry.union_all()],
            "BoroName": ["Staten Island"],
            "BoroCode": [5],
            "manhattan_bronx": [5],
        },
        geometry=nybb_polydf.geometry.name,
        crs=nybb_polydf.crs,
    )
    assert_frame_equal(expected, test, check_column_type=False)


def test_dissolve_none_mean(nybb_polydf):
    test = nybb_polydf.dissolve(aggfunc="mean", numeric_only=True)
    expected = GeoDataFrame(
        {
            nybb_polydf.geometry.name: [nybb_polydf.geometry.union_all()],
            "BoroCode": [3.0],
            "manhattan_bronx": [5.4],
        },
        geometry=nybb_polydf.geometry.name,
        crs=nybb_polydf.crs,
    )
    assert_frame_equal(expected, test, check_column_type=False)


def test_dissolve_level():
    gdf = geopandas.GeoDataFrame(
        {
            "a": [1, 1, 2, 2],
            "b": [3, 4, 4, 4],
            "c": [3, 4, 5, 6],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "POINT (1 1)", "POINT (2 2)", "POINT (3 3)"]
            ),
        }
    ).set_index(["a", "b", "c"])

    expected_a = geopandas.GeoDataFrame(
        {
            "a": [1, 2],
            "geometry": geopandas.array.from_wkt(
                ["MULTIPOINT (0 0, 1 1)", "MULTIPOINT (2 2, 3 3)"]
            ),
        }
    ).set_index("a")
    expected_b = geopandas.GeoDataFrame(
        {
            "b": [3, 4],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "MULTIPOINT (1 1, 2 2, 3 3)"]
            ),
        }
    ).set_index("b")
    expected_ab = geopandas.GeoDataFrame(
        {
            "a": [1, 1, 2],
            "b": [3, 4, 4],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "POINT (1 1)", "MULTIPOINT (2 2, 3 3)"]
            ),
        }
    ).set_index(["a", "b"])

    assert_frame_equal(expected_a, gdf.dissolve(level=0))
    assert_frame_equal(expected_a, gdf.dissolve(level="a"))
    assert_frame_equal(expected_b, gdf.dissolve(level=1))
    assert_frame_equal(expected_b, gdf.dissolve(level="b"))
    assert_frame_equal(expected_ab, gdf.dissolve(level=[0, 1]))
    assert_frame_equal(expected_ab, gdf.dissolve(level=["a", "b"]))


def test_dissolve_sort():
    gdf = geopandas.GeoDataFrame(
        {
            "a": [2, 1, 1],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "POINT (1 1)", "POINT (2 2)"]
            ),
        }
    )

    expected_unsorted = geopandas.GeoDataFrame(
        {
            "a": [2, 1],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "MULTIPOINT (1 1, 2 2)"]
            ),
        }
    ).set_index("a")
    expected_sorted = expected_unsorted.sort_index()

    assert_frame_equal(expected_sorted, gdf.dissolve("a"))
    assert_frame_equal(expected_unsorted, gdf.dissolve("a", sort=False))


def test_dissolve_categorical():
    gdf = geopandas.GeoDataFrame(
        {
            "cat": pd.Categorical(["a", "a", "b", "b"]),
            "noncat": [1, 1, 1, 2],
            "to_agg": [1, 2, 3, 4],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "POINT (1 1)", "POINT (2 2)", "POINT (3 3)"]
            ),
        }
    )

    # when observed=False we get an additional observation
    # that wasn't in the original data
    none_val = "GEOMETRYCOLLECTION EMPTY" if PANDAS_GE_30 else None
    expected_gdf_observed_false = geopandas.GeoDataFrame(
        {
            "cat": pd.Categorical(["a", "a", "b", "b"]),
            "noncat": [1, 2, 1, 2],
            "geometry": geopandas.array.from_wkt(
                [
                    "MULTIPOINT (0 0, 1 1)",
                    none_val,
                    "POINT (2 2)",
                    "POINT (3 3)",
                ]
            ),
            "to_agg": [1, None, 3, 4],
        }
    ).set_index(["cat", "noncat"])

    # when observed=True we do not get any additional observations
    expected_gdf_observed_true = geopandas.GeoDataFrame(
        {
            "cat": pd.Categorical(["a", "b", "b"]),
            "noncat": [1, 1, 2],
            "geometry": geopandas.array.from_wkt(
                ["MULTIPOINT (0 0, 1 1)", "POINT (2 2)", "POINT (3 3)"]
            ),
            "to_agg": [1, 3, 4],
        }
    ).set_index(["cat", "noncat"])

    assert_frame_equal(expected_gdf_observed_false, gdf.dissolve(["cat", "noncat"]))
    assert_frame_equal(
        expected_gdf_observed_true, gdf.dissolve(["cat", "noncat"], observed=True)
    )


def test_dissolve_dropna():
    gdf = geopandas.GeoDataFrame(
        {
            "a": [1, 1, None],
            "geometry": geopandas.array.from_wkt(
                ["POINT (0 0)", "POINT (1 1)", "POINT (2 2)"]
            ),
        }
    )

    expected_with_na = geopandas.GeoDataFrame(
        {
            "a": [1.0, np.nan],
            "geometry": geopandas.array.from_wkt(
                ["MULTIPOINT (0 0, 1 1)", "POINT (2 2)"]
            ),
        }
    ).set_index("a")
    expected_no_na = geopandas.GeoDataFrame(
        {
            "a": [1.0],
            "geometry": geopandas.array.from_wkt(["MULTIPOINT (0 0, 1 1)"]),
        }
    ).set_index("a")

    assert_frame_equal(expected_with_na, gdf.dissolve("a", dropna=False))
    assert_frame_equal(expected_no_na, gdf.dissolve("a"))


def test_dissolve_dropna_warn(nybb_polydf):
    # No warning with default params
    with warnings.catch_warnings(record=True) as record:
        nybb_polydf.dissolve()

    for r in record:
        assert "dropna kwarg is not supported" not in str(r.message)


def test_dissolve_multi_agg(nybb_polydf, merged_shapes):
    merged_shapes[("BoroCode", "min")] = [3, 1]
    merged_shapes[("BoroCode", "max")] = [5, 2]
    merged_shapes[("BoroName", "count")] = [3, 2]

    with warnings.catch_warnings():
        warnings.simplefilter(action="error")
        test = nybb_polydf.dissolve(
            by="manhattan_bronx",
            aggfunc={
                "BoroCode": ["min", "max"],
                "BoroName": "count",
            },
        )

    assert_geodataframe_equal(test, merged_shapes)


@pytest.mark.parametrize("method", ["coverage", "disjoint_subset"])
def test_dissolve_method(nybb_polydf, method):
    if method == "disjoint_subset" and not (GEOS_GE_312 and SHAPELY_GE_21):
        pytest.skip("Unsupported shapely/GEOS.")
    manhattan_bronx = nybb_polydf.loc[3:4]
    others = nybb_polydf.loc[0:2]

    collapsed = [
        others.geometry.union_all(method=method),
        manhattan_bronx.geometry.union_all(method=method),
    ]
    merged_shapes = GeoDataFrame(
        {"myshapes": collapsed},
        geometry="myshapes",
        index=pd.Index([5, 6], name="manhattan_bronx"),
        crs=nybb_polydf.crs,
    )

    merged_shapes["BoroName"] = ["Staten Island", "Manhattan"]
    merged_shapes["BoroCode"] = [5, 1]

    test = nybb_polydf.dissolve("manhattan_bronx", method=method)
    assert_frame_equal(merged_shapes, test, check_column_type=False)

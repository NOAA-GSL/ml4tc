"""Plots occlusion maps."""

import copy
import argparse
import numpy
import matplotlib
matplotlib.use('agg')
from matplotlib import pyplot
from gewittergefahr.gg_utils import general_utils as gg_general_utils
from gewittergefahr.gg_utils import time_conversion
from gewittergefahr.gg_utils import file_system_utils
from gewittergefahr.plotting import imagemagick_utils
from ml4tc.io import example_io
from ml4tc.io import border_io
from ml4tc.utils import normalization
from ml4tc.machine_learning import occlusion
from ml4tc.machine_learning import neural_net
from ml4tc.plotting import plotting_utils
from ml4tc.plotting import satellite_plotting
from ml4tc.plotting import predictor_plotting

SEPARATOR_STRING = '\n\n' + '*' * 50 + '\n\n'
TIME_FORMAT = '%Y-%m-%d-%H%M%S'

MAX_COLOUR_PERCENTILE = 99.
COLOUR_BAR_FONT_SIZE = 12

FIGURE_RESOLUTION_DPI = 300
PANEL_SIZE_PX = int(2.5e6)

OCCLUSION_FILE_ARG_NAME = 'input_occlusion_file_name'
EXAMPLE_DIR_ARG_NAME = 'input_example_dir_name'
NORMALIZATION_FILE_ARG_NAME = 'input_normalization_file_name'
PLOT_NORMALIZED_ARG_NAME = 'plot_normalized_occlusion'
COLOUR_MAP_ARG_NAME = 'colour_map_name'
SMOOTHING_RADIUS_ARG_NAME = 'smoothing_radius_px'
OUTPUT_DIR_ARG_NAME = 'output_dir_name'

OCCLUSION_FILE_HELP_STRING = (
    'Path to file with occlusion maps.  Will be read by `occlusion.read_file`.'
)
EXAMPLE_DIR_HELP_STRING = (
    'Name of directory with input examples.  Files therein will be found by '
    '`example_io.find_file` and read by `example_io.read_file`.'
)
NORMALIZATION_FILE_HELP_STRING = (
    'Path to file with normalization params (will be used to denormalize '
    'brightness-temperature maps before plotting).  Will be read by '
    '`normalization.read_file`.'
)
PLOT_NORMALIZED_HELP_STRING = (
    'Boolean flag.  If 1 (0), will plot normalized (standard) occlusion maps.'
)
COLOUR_MAP_HELP_STRING = (
    'Name of colour scheme for occlusion map.  Must be accepted by '
    '`matplotlib.pyplot.get_cmap`.'
)
SMOOTHING_RADIUS_HELP_STRING = (
    'Smoothing radius (number of pixels) for occlusion maps.  If you do '
    'not want to smooth, make this 0 or negative.'
)
OUTPUT_DIR_HELP_STRING = 'Name of output directory.  Images will be saved here.'

INPUT_ARG_PARSER = argparse.ArgumentParser()
INPUT_ARG_PARSER.add_argument(
    '--' + OCCLUSION_FILE_ARG_NAME, type=str, required=True,
    help=OCCLUSION_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + EXAMPLE_DIR_ARG_NAME, type=str, required=True,
    help=EXAMPLE_DIR_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + NORMALIZATION_FILE_ARG_NAME, type=str, required=True,
    help=NORMALIZATION_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + PLOT_NORMALIZED_ARG_NAME, type=int, required=True,
    help=PLOT_NORMALIZED_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + COLOUR_MAP_ARG_NAME, type=str, required=False, default='BuGn',
    help=COLOUR_MAP_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + SMOOTHING_RADIUS_ARG_NAME, type=float, required=False, default=-1,
    help=SMOOTHING_RADIUS_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + OUTPUT_DIR_ARG_NAME, type=str, required=True,
    help=OUTPUT_DIR_HELP_STRING
)


def _smooth_maps(occlusion_dict, smoothing_radius_px, plot_normalized_occlusion):
    """Smooths occlusion maps via Gaussian filter.

    :param occlusion_dict: Dictionary returned by `occlusion.read_file`.
    :param smoothing_radius_px: e-folding radius (num pixels).
    :param plot_normalized_occlusion: See documentation at top of file.
    :return: occlusion_dict: Same as input but with smoothed maps.
    """

    print((
        'Smoothing occlusion maps with Gaussian filter (e-folding radius of '
        '{0:.1f} grid cells)...'
    ).format(
        smoothing_radius_px
    ))

    if plot_normalized_occlusion:
        this_key = occlusion.NORMALIZED_OCCLUSION_KEY
    else:
        this_key = occlusion.OCCLUSION_PROBS_KEY

    occlusion_matrix = occlusion_dict[this_key]
    num_examples = occlusion_matrix.shape[0]

    for i in range(num_examples):
        occlusion_matrix[i, ...] = gg_general_utils.apply_gaussian_filter(
            input_matrix=occlusion_matrix[i, ...],
            e_folding_radius_grid_cells=smoothing_radius_px
        )

    occlusion_dict[this_key] = occlusion_matrix
    return occlusion_dict


def _plot_occlusion_map_one_example(
        data_dict, occlusion_dict, plot_normalized_occlusion,
        model_metadata_dict, cyclone_id_string, init_time_unix_sec,
        normalization_table_xarray, border_latitudes_deg_n,
        border_longitudes_deg_e, colour_map_object, output_dir_name):
    """Plots occlusion map for one example.

    P = number of points in border set

    :param data_dict: Dictionary returned by `neural_net.create_inputs`.
    :param occlusion_dict: Dictionary returned by `occlusion.read_file`.
    :param plot_normalized_occlusion: Boolean flag.  If True (False), will plot
        normalized (standard) occlusion map.
    :param model_metadata_dict: Dictionary returned by
        `neural_net.read_metafile`.
    :param cyclone_id_string: Cyclone ID (must be accepted by
        `satellite_utils.parse_cyclone_id`).
    :param init_time_unix_sec: Forecast-initialization time.
    :param normalization_table_xarray: xarray table returned by
        `normalization.read_file`.
    :param border_latitudes_deg_n: length-P numpy array of latitudes
        (deg north).
    :param border_longitudes_deg_e: length-P numpy array of longitudes
        (deg east).
    :param colour_map_object: Colour scheme (instance of
        `matplotlib.pyplot.cm`).
    :param output_dir_name: Name of output directory.  Figure will be saved
        here.
    """

    predictor_example_index = numpy.where(
        data_dict[neural_net.INIT_TIMES_KEY] == init_time_unix_sec
    )[0][0]
    occlusion_example_index = numpy.where(
        occlusion_dict[occlusion.INIT_TIMES_KEY] == init_time_unix_sec
    )[0][0]

    predictor_matrices_one_example = [
        None if p is None else p[[predictor_example_index], ...]
        for p in data_dict[neural_net.PREDICTOR_MATRICES_KEY]
    ]

    if plot_normalized_occlusion:
        this_key = occlusion.NORMALIZED_OCCLUSION_KEY
    else:
        this_key = occlusion.OCCLUSION_PROBS_KEY

    occlusion_matrix_one_example = (
        occlusion_dict[this_key][[occlusion_example_index], ...]
    )

    grid_latitude_matrix_deg_n = data_dict[
        neural_net.GRID_LATITUDE_MATRIX_KEY
    ][predictor_example_index, ...]

    grid_longitude_matrix_deg_e = data_dict[
        neural_net.GRID_LONGITUDE_MATRIX_KEY
    ][predictor_example_index, ...]

    figure_objects, axes_objects, pathless_output_file_names = (
        predictor_plotting.plot_brightness_temp_one_example(
            predictor_matrices_one_example=predictor_matrices_one_example,
            model_metadata_dict=model_metadata_dict,
            cyclone_id_string=cyclone_id_string,
            init_time_unix_sec=init_time_unix_sec,
            grid_latitude_matrix_deg_n=grid_latitude_matrix_deg_n,
            grid_longitude_matrix_deg_e=grid_longitude_matrix_deg_e,
            normalization_table_xarray=normalization_table_xarray,
            border_latitudes_deg_n=border_latitudes_deg_n,
            border_longitudes_deg_e=border_longitudes_deg_e
        )
    )

    validation_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )
    num_model_lag_times = len(
        validation_option_dict[neural_net.SATELLITE_LAG_TIMES_KEY]
    )
    panel_file_names = [''] * num_model_lag_times

    if plot_normalized_occlusion:
        finite_values = occlusion_matrix_one_example[
            numpy.isfinite(occlusion_matrix_one_example)
        ]
        max_contour_value = numpy.percentile(
            numpy.absolute(finite_values), MAX_COLOUR_PERCENTILE
        )
        min_contour_value = numpy.percentile(
            numpy.absolute(finite_values), 100. - MAX_COLOUR_PERCENTILE
        )
    else:
        max_contour_value = numpy.percentile(
            occlusion_matrix_one_example, MAX_COLOUR_PERCENTILE
        )
        min_contour_value = numpy.percentile(
            occlusion_matrix_one_example, 100. - MAX_COLOUR_PERCENTILE
        )

    for k in range(num_model_lag_times):
        if plot_normalized_occlusion:
            min_contour_value, max_contour_value = (
                satellite_plotting.plot_saliency(
                    saliency_matrix=occlusion_matrix_one_example[0, ...],
                    axes_object=axes_objects[k],
                    latitudes_deg_n=grid_latitude_matrix_deg_n[:, k],
                    longitudes_deg_e=grid_longitude_matrix_deg_e[:, k],
                    min_abs_contour_value=min_contour_value,
                    max_abs_contour_value=max_contour_value,
                    half_num_contours=10, colour_map_object=colour_map_object
                )
            )
        else:
            min_contour_value, max_contour_value = (
                satellite_plotting.plot_class_activation(
                    class_activation_matrix=occlusion_matrix_one_example[
                        0, ...],
                    axes_object=axes_objects[k],
                    latitudes_deg_n=grid_latitude_matrix_deg_n[:, k],
                    longitudes_deg_e=grid_longitude_matrix_deg_e[:, k],
                    min_contour_value=min_contour_value,
                    max_contour_value=max_contour_value,
                    num_contours=15, colour_map_object=colour_map_object
                )
            )

        panel_file_names[k] = '{0:s}/{1:s}'.format(
            output_dir_name, pathless_output_file_names[k]
        )
        print('Saving figure to file: "{0:s}"...'.format(
            panel_file_names[k]
        ))
        figure_objects[k].savefig(
            panel_file_names[k], dpi=FIGURE_RESOLUTION_DPI,
            pad_inches=0, bbox_inches='tight'
        )
        pyplot.close(figure_objects[k])

        imagemagick_utils.resize_image(
            input_file_name=panel_file_names[k],
            output_file_name=panel_file_names[k],
            output_size_pixels=PANEL_SIZE_PX
        )

    init_time_string = time_conversion.unix_sec_to_string(
        init_time_unix_sec, TIME_FORMAT
    )
    concat_figure_file_name = (
        '{0:s}/{1:s}_{2:s}_brightness_temp_concat.jpg'
    ).format(
        output_dir_name, cyclone_id_string, init_time_string
    )
    plotting_utils.concat_panels(
        panel_file_names=panel_file_names,
        concat_figure_file_name=concat_figure_file_name
    )

    this_colour_map_object, colour_norm_object = (
        satellite_plotting.get_colour_scheme()
    )
    plotting_utils.add_colour_bar(
        figure_file_name=concat_figure_file_name,
        colour_map_object=this_colour_map_object,
        colour_norm_object=colour_norm_object,
        orientation_string='vertical', font_size=COLOUR_BAR_FONT_SIZE,
        cbar_label_string='Brightness temp (K)',
        tick_label_format_string='{0:d}'
    )

    colour_norm_object = pyplot.Normalize(
        vmin=min_contour_value, vmax=max_contour_value
    )
    label_string = (
        'Absolute normalized probability decrease' if plot_normalized_occlusion
        else 'Post-occlusion probability'
    )
    plotting_utils.add_colour_bar(
        figure_file_name=concat_figure_file_name,
        colour_map_object=colour_map_object,
        colour_norm_object=colour_norm_object,
        orientation_string='vertical', font_size=COLOUR_BAR_FONT_SIZE,
        cbar_label_string=label_string, tick_label_format_string='{0:.2g}'
    )


def _run(occlusion_file_name, example_dir_name, normalization_file_name,
         colour_map_name, smoothing_radius_px, plot_normalized_occlusion,
         output_dir_name):
    """Plots class-activation maps.

    This is effectively the main method.

    :param occlusion_file_name: See documentation at top of file.
    :param example_dir_name: Same.
    :param normalization_file_name: Same.
    :param colour_map_name: Same.
    :param smoothing_radius_px: Same.
    :param plot_normalized_occlusion: Same.
    :param output_dir_name: Same.
    """

    colour_map_object = pyplot.get_cmap(colour_map_name)
    file_system_utils.mkdir_recursive_if_necessary(
        directory_name=output_dir_name
    )

    # Read files.
    print('Reading data from: "{0:s}"...'.format(occlusion_file_name))
    occlusion_dict = occlusion.read_file(occlusion_file_name)

    if smoothing_radius_px > 0:
        occlusion_dict = _smooth_maps(
            occlusion_dict=occlusion_dict,
            smoothing_radius_px=smoothing_radius_px,
            plot_normalized_occlusion=plot_normalized_occlusion
        )

    model_file_name = occlusion_dict[occlusion.MODEL_FILE_KEY]
    model_metafile_name = neural_net.find_metafile(
        model_file_name=model_file_name, raise_error_if_missing=True
    )

    print('Reading metadata from: "{0:s}"...'.format(model_metafile_name))
    model_metadata_dict = neural_net.read_metafile(model_metafile_name)
    base_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )

    print('Reading data from: "{0:s}"...'.format(normalization_file_name))
    normalization_table_xarray = normalization.read_file(
        normalization_file_name
    )

    border_latitudes_deg_n, border_longitudes_deg_e = border_io.read_file()

    # Find example files.
    unique_cyclone_id_strings = numpy.unique(
        numpy.array(occlusion_dict[occlusion.CYCLONE_IDS_KEY])
    )
    num_cyclones = len(unique_cyclone_id_strings)

    unique_example_file_names = [
        example_io.find_file(
            directory_name=example_dir_name, cyclone_id_string=c,
            prefer_zipped=False, allow_other_format=True,
            raise_error_if_missing=True
        )
        for c in unique_cyclone_id_strings
    ]

    # Plot occlusion maps.
    for i in range(num_cyclones):
        option_dict = copy.deepcopy(base_option_dict)
        option_dict[neural_net.EXAMPLE_FILE_KEY] = unique_example_file_names[i]

        print(SEPARATOR_STRING)
        data_dict = neural_net.create_inputs(option_dict)
        print(SEPARATOR_STRING)

        example_indices = numpy.where(
            numpy.array(occlusion_dict[occlusion.CYCLONE_IDS_KEY]) ==
            unique_cyclone_id_strings[i]
        )[0]

        for j in example_indices:
            _plot_occlusion_map_one_example(
                data_dict=data_dict,
                occlusion_dict=occlusion_dict,
                plot_normalized_occlusion=plot_normalized_occlusion,
                model_metadata_dict=model_metadata_dict,
                cyclone_id_string=unique_cyclone_id_strings[i],
                init_time_unix_sec=occlusion_dict[occlusion.INIT_TIMES_KEY][j],
                normalization_table_xarray=normalization_table_xarray,
                border_latitudes_deg_n=border_latitudes_deg_n,
                border_longitudes_deg_e=border_longitudes_deg_e,
                colour_map_object=colour_map_object,
                output_dir_name=output_dir_name
            )


if __name__ == '__main__':
    INPUT_ARG_OBJECT = INPUT_ARG_PARSER.parse_args()

    _run(
        occlusion_file_name=getattr(INPUT_ARG_OBJECT, OCCLUSION_FILE_ARG_NAME),
        example_dir_name=getattr(INPUT_ARG_OBJECT, EXAMPLE_DIR_ARG_NAME),
        normalization_file_name=getattr(
            INPUT_ARG_OBJECT, NORMALIZATION_FILE_ARG_NAME
        ),
        plot_normalized_occlusion=bool(getattr(
            INPUT_ARG_OBJECT, PLOT_NORMALIZED_ARG_NAME
        )),
        colour_map_name=getattr(INPUT_ARG_OBJECT, COLOUR_MAP_ARG_NAME),
        smoothing_radius_px=getattr(
            INPUT_ARG_OBJECT, SMOOTHING_RADIUS_ARG_NAME
        ),
        output_dir_name=getattr(INPUT_ARG_OBJECT, OUTPUT_DIR_ARG_NAME)
    )

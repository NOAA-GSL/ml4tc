"""Plots all predictors (scalars and brightness-temp maps) for a given model."""

import os
import shutil
import argparse
import numpy
import xarray
from gewittergefahr.gg_utils import time_conversion
from gewittergefahr.gg_utils import file_system_utils
from gewittergefahr.plotting import imagemagick_utils
from ml4tc.io import example_io
from ml4tc.io import border_io
from ml4tc.io import ships_io
from ml4tc.io import prediction_io
from ml4tc.utils import example_utils
from ml4tc.utils import satellite_utils
from ml4tc.utils import general_utils
from ml4tc.utils import normalization
from ml4tc.machine_learning import neural_net
from ml4tc.scripts import plot_satellite
from ml4tc.scripts import \
    plot_scalar_satellite_predictors as plot_scalar_satellite
from ml4tc.scripts import plot_ships_predictors as plot_ships

SEPARATOR_STRING = '\n\n' + '*' * 50 + '\n\n'
TIME_FORMAT = '%Y-%m-%d-%H%M%S'

MINUTES_TO_SECONDS = 60
HOURS_TO_SECONDS = 3600
METRES_PER_SECOND_TO_KT = 3.6 / 1.852

PANEL_SIZE_PX = int(2.5e6)
CONCAT_FIGURE_SIZE_PX = int(1e7)

MODEL_METAFILE_ARG_NAME = 'input_model_metafile_name'
EXAMPLE_FILE_ARG_NAME = 'input_norm_example_file_name'
NORMALIZATION_FILE_ARG_NAME = 'input_normalization_file_name'
PREDICTION_FILE_ARG_NAME = 'input_prediction_file_name'
INIT_TIMES_ARG_NAME = 'init_time_strings'
FIRST_TIME_ARG_NAME = 'first_init_time_string'
LAST_TIME_ARG_NAME = 'last_init_time_string'
OUTPUT_DIR_ARG_NAME = 'output_dir_name'

MODEL_METAFILE_HELP_STRING = (
    'Path to metafile for model.  Will be read by `neural_net.read_metafile`.'
)
EXAMPLE_FILE_HELP_STRING = (
    'Path to file with normalized learning examples for one cyclone.  Will be '
    'read by `example_io.read_file`.'
)
NORMALIZATION_FILE_HELP_STRING = (
    'Path to file with normalization params (will be used to denormalize '
    'brightness-temperature maps before plotting).  Will be read by '
    '`normalization.read_file`.'
)
PREDICTION_FILE_HELP_STRING = (
    'Path to file with predictions and targets.  Will be read by '
    '`prediction_io.read_file`.  If you do not want to plot predictions and '
    'targets, leave this argument alone.'
)
INIT_TIMES_HELP_STRING = (
    'List of initialization times (format "yyyy-mm-dd-HHMMSS").  '
    'Predictors will be plotted for each of these init times.'
)
FIRST_TIME_HELP_STRING = (
    '[used only if `{0:s}` is left alone] First init time (format '
    '"yyyy-mm-dd-HHMMSS").'
).format(INIT_TIMES_ARG_NAME)

LAST_TIME_HELP_STRING = (
    '[used only if `{0:s}` is left alone] Last init time (format '
    '"yyyy-mm-dd-HHMMSS").'
).format(INIT_TIMES_ARG_NAME)

OUTPUT_DIR_HELP_STRING = 'Name of output directory.  Images will be saved here.'

INPUT_ARG_PARSER = argparse.ArgumentParser()
INPUT_ARG_PARSER.add_argument(
    '--' + MODEL_METAFILE_ARG_NAME, type=str, required=True,
    help=MODEL_METAFILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + EXAMPLE_FILE_ARG_NAME, type=str, required=True,
    help=EXAMPLE_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + NORMALIZATION_FILE_ARG_NAME, type=str, required=True,
    help=NORMALIZATION_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + PREDICTION_FILE_ARG_NAME, type=str, required=False, default='',
    help=PREDICTION_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + INIT_TIMES_ARG_NAME, type=str, nargs='+', required=False,
    default=[''], help=INIT_TIMES_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + FIRST_TIME_ARG_NAME, type=str, required=False, default='',
    help=FIRST_TIME_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + LAST_TIME_ARG_NAME, type=str, required=False, default='',
    help=LAST_TIME_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + OUTPUT_DIR_ARG_NAME, type=str, required=True,
    help=OUTPUT_DIR_HELP_STRING
)


def _get_intensities(example_table_xarray, init_times_unix_sec,
                     model_metadata_dict):
    """Returns current and future storm intensities.

    T = number of forecast-initialization times

    :param example_table_xarray: xarray table returned by
        `example_io.read_file`.
    :param init_times_unix_sec: length-T numpy array of forecast-initialization
        times.
    :param model_metadata_dict: Dictionary returned by
        `neural_net.read_metafile`.
    :return: current_intensities_kt: length-T numpy array of current intensities
        (knots).
    :return: future_intensities_kt: length-T numpy array of future intensities
        (knots).
    """

    xt = example_table_xarray
    these_times_unix_sec = (
        xt.coords[example_utils.SHIPS_VALID_TIME_DIM].values
    )
    good_indices = numpy.array([
        numpy.where(these_times_unix_sec == t)[0][0]
        for t in init_times_unix_sec
    ], dtype=int)

    current_intensities_kt = METRES_PER_SECOND_TO_KT * (
        xt[example_utils.STORM_INTENSITY_KEY].values[good_indices]
    )
    current_intensities_kt = numpy.round(current_intensities_kt).astype(int)

    validation_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )
    lead_time_sec = (
        HOURS_TO_SECONDS * validation_option_dict[neural_net.LEAD_TIME_KEY]
    )
    good_indices_2d_list = [
        numpy.where(these_times_unix_sec == t)[0]
        for t in init_times_unix_sec + lead_time_sec
    ]
    good_indices = numpy.array([
        -1 if len(idcs) == 0 else idcs[0]
        for idcs in good_indices_2d_list
    ], dtype=int)

    future_intensities_kt = METRES_PER_SECOND_TO_KT * (
        xt[example_utils.STORM_INTENSITY_KEY].values[good_indices]
    )
    future_intensities_kt[good_indices == -1] = 0.
    future_intensities_kt = numpy.round(future_intensities_kt).astype(int)

    return current_intensities_kt, future_intensities_kt


def _get_predictions_and_targets(prediction_file_name, cyclone_id_string,
                                 init_times_unix_sec):
    """Returns prediction and target for each forecast-initialization time.

    T = number of forecast-initialization times
    K = number of classes

    :param prediction_file_name: Path to input file.  Will be read by
        `prediction_io.read_file`.
    :param cyclone_id_string: ID for desired cyclone.
    :param init_times_unix_sec: length-T numpy array of desired init times.
    :return: forecast_prob_matrix: T-by-K numpy array of forecast class
        probabilities.
    :return: target_classes: length-T numpy array of target classes (integers in
        range 0...[K - 1]).
    """

    print('Reading data from: "{0:s}"...'.format(prediction_file_name))
    prediction_dict = prediction_io.read_file(prediction_file_name)

    good_flags = numpy.array([
        cid == cyclone_id_string
        for cid in prediction_dict[prediction_io.CYCLONE_IDS_KEY]
    ], dtype=bool)

    good_indices = numpy.where(good_flags)[0]
    these_times_unix_sec = (
        prediction_dict[prediction_io.INIT_TIMES_KEY][good_indices]
    )
    good_subindices = numpy.array([
        numpy.where(these_times_unix_sec == t)[0][0]
        for t in init_times_unix_sec
    ], dtype=int)

    good_indices = good_indices[good_subindices]
    target_classes = (
        prediction_dict[prediction_io.TARGET_CLASSES_KEY][good_indices]
    )
    forecast_prob_matrix = (
        prediction_dict[prediction_io.PROBABILITY_MATRIX_KEY][
            good_indices, ...
        ]
    )

    return forecast_prob_matrix, target_classes


def _concat_panels(panel_file_names, concat_figure_file_name):
    """Concatenates panels into one figure.

    :param panel_file_names: 1-D list of paths to input image files.
    :param concat_figure_file_name: Path to output image file.
    """

    print('Concatenating panels to: "{0:s}"...'.format(
        concat_figure_file_name
    ))

    num_panels = len(panel_file_names)
    num_panel_rows = int(numpy.floor(
        numpy.sqrt(num_panels)
    ))
    num_panel_columns = int(numpy.ceil(
        float(num_panels) / num_panel_rows
    ))

    if num_panels == 1:
        shutil.move(panel_file_names[0], concat_figure_file_name)
    else:
        imagemagick_utils.concatenate_images(
            input_file_names=panel_file_names,
            num_panel_rows=num_panel_rows,
            num_panel_columns=num_panel_columns,
            output_file_name=concat_figure_file_name
        )

    imagemagick_utils.resize_image(
        input_file_name=concat_figure_file_name,
        output_file_name=concat_figure_file_name,
        output_size_pixels=CONCAT_FIGURE_SIZE_PX
    )
    imagemagick_utils.trim_whitespace(
        input_file_name=concat_figure_file_name,
        output_file_name=concat_figure_file_name
    )

    if num_panels == 1:
        return

    for this_panel_file_name in panel_file_names:
        os.remove(this_panel_file_name)


def _plot_brightness_temps(
        example_table_xarray, normalization_table_xarray, model_metadata_dict,
        predictor_matrices, init_times_unix_sec, info_strings,
        border_latitudes_deg_n, border_longitudes_deg_e, output_dir_name):
    """Plots one brightness-temp map for each init time and lag time.

    P = number of points in border set

    :param example_table_xarray: xarray table returned by
        `example_io.read_file`.
    :param normalization_table_xarray: xarray table returned by
        `normalization.read_file`.
    :param model_metadata_dict: Dictionary returned by
        `neural_net.read_metafile`.
    :param predictor_matrices: See output doc for `neural_net.create_inputs`.
    :param init_times_unix_sec: Same.
    :param info_strings: 1-D list of info strings, one per init time.
    :param border_latitudes_deg_n: length-P numpy array of latitudes (deg N).
    :param border_longitudes_deg_e: length-P numpy array of longitudes (deg E).
    :param output_dir_name: Name of output directory.  Figures will be saved
        here.
    """

    xt = example_table_xarray
    nt = normalization_table_xarray
    validation_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )

    # Denormalize brightness temperatures.
    predictor_names_norm = list(
        nt.coords[normalization.SATELLITE_PREDICTOR_GRIDDED_DIM].values
    )
    k = predictor_names_norm.index(satellite_utils.BRIGHTNESS_TEMPERATURE_KEY)
    training_values = (
        nt[normalization.SATELLITE_PREDICTORS_GRIDDED_KEY].values[:, k]
    )
    training_values = training_values[numpy.isfinite(training_values)]

    brightness_temp_matrix_kelvins = normalization._denorm_one_variable(
        normalized_values_new=predictor_matrices[0],
        actual_values_training=training_values
    )[..., 0]

    # Housekeeping.
    num_init_times = len(init_times_unix_sec)
    lag_times_sec = (
        MINUTES_TO_SECONDS *
        validation_option_dict[neural_net.SATELLITE_LAG_TIMES_KEY]
    )
    num_lag_times = len(lag_times_sec)

    num_grid_rows = brightness_temp_matrix_kelvins.shape[1]
    num_grid_columns = brightness_temp_matrix_kelvins.shape[2]
    grid_row_indices = numpy.linspace(
        0, num_grid_rows - 1, num=num_grid_rows, dtype=int
    )
    grid_column_indices = numpy.linspace(
        0, num_grid_columns - 1, num=num_grid_columns, dtype=int
    )

    # Do actual stuff (plot maps of denormalized brightness temperature).
    for i in range(num_init_times):
        panel_file_names = [''] * num_lag_times

        for j in range(num_lag_times):
            valid_time_unix_sec = init_times_unix_sec[i] - lag_times_sec[j]
            satellite_metadata_dict = {
                satellite_utils.GRID_ROW_DIM: grid_row_indices,
                satellite_utils.GRID_COLUMN_DIM: grid_column_indices,
                satellite_utils.TIME_DIM:
                    numpy.array([valid_time_unix_sec], dtype=int)
            }

            k = numpy.argmin(numpy.absolute(
                xt.coords[example_utils.SATELLITE_TIME_DIM].values -
                valid_time_unix_sec
            ))
            grid_latitudes_deg_n = (
                xt[satellite_utils.GRID_LATITUDE_KEY].values[k, :]
            )
            grid_longitudes_deg_e = (
                xt[satellite_utils.GRID_LONGITUDE_KEY].values[k, :]
            )
            cyclone_id_string = xt[satellite_utils.CYCLONE_ID_KEY].values[k]
            these_dim_3d = (
                satellite_utils.TIME_DIM,
                satellite_utils.GRID_ROW_DIM, satellite_utils.GRID_COLUMN_DIM
            )

            satellite_data_dict = {
                satellite_utils.CYCLONE_ID_KEY: (
                    (satellite_utils.TIME_DIM,),
                    [cyclone_id_string]
                ),
                satellite_utils.BRIGHTNESS_TEMPERATURE_KEY: (
                    these_dim_3d,
                    brightness_temp_matrix_kelvins[[i], ..., j]
                ),
                satellite_utils.GRID_LATITUDE_KEY: (
                    (satellite_utils.TIME_DIM, satellite_utils.GRID_ROW_DIM),
                    numpy.expand_dims(grid_latitudes_deg_n, axis=0)
                ),
                satellite_utils.GRID_LONGITUDE_KEY: (
                    (satellite_utils.TIME_DIM, satellite_utils.GRID_COLUMN_DIM),
                    numpy.expand_dims(grid_longitudes_deg_e, axis=0)
                )
            }

            satellite_table_xarray = xarray.Dataset(
                data_vars=satellite_data_dict, coords=satellite_metadata_dict
            )
            panel_file_names[j] = plot_satellite.plot_one_satellite_image(
                satellite_table_xarray=satellite_table_xarray, time_index=0,
                border_latitudes_deg_n=border_latitudes_deg_n,
                border_longitudes_deg_e=border_longitudes_deg_e,
                output_dir_name=output_dir_name,
                info_string=info_strings[i] if lag_times_sec[j] == 0 else None
            )
            imagemagick_utils.resize_image(
                input_file_name=panel_file_names[j],
                output_file_name=panel_file_names[j],
                output_size_pixels=PANEL_SIZE_PX
            )

        concat_figure_file_name = '{0:s}/{1:s}_brightness_temp.jpg'.format(
            output_dir_name,
            time_conversion.unix_sec_to_string(
                init_times_unix_sec[i], TIME_FORMAT
            )
        )
        _concat_panels(
            panel_file_names=panel_file_names,
            concat_figure_file_name=concat_figure_file_name
        )


def _plot_scalar_satellite_predictors(
        example_table_xarray, model_metadata_dict, predictor_matrices,
        init_times_unix_sec, info_strings, output_dir_name):
    """Plots scalar satellite predictors for each init time and lag time.

    :param example_table_xarray: See doc for `_plot_brightness_temps`.
    :param model_metadata_dict: Same.
    :param predictor_matrices: Same.
    :param init_times_unix_sec: Same.
    :param info_strings: Same.
    :param output_dir_name: Same.
    """

    # Housekeeping.
    xt = example_table_xarray
    validation_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )

    num_init_times = len(init_times_unix_sec)
    lag_times_sec = (
        MINUTES_TO_SECONDS *
        validation_option_dict[neural_net.SATELLITE_LAG_TIMES_KEY]
    )
    num_lag_times = len(lag_times_sec)

    num_predictors = predictor_matrices[1].shape[-1]
    predictor_indices = numpy.linspace(
        0, num_predictors - 1, num=num_predictors, dtype=int
    )

    # Do actual stuff (plot bar graphs with normalized predictors).
    for i in range(num_init_times):
        panel_file_names = [''] * num_lag_times

        for j in range(num_lag_times):
            valid_time_unix_sec = init_times_unix_sec[i] - lag_times_sec[j]
            cyclone_id_string = xt[satellite_utils.CYCLONE_ID_KEY].values[0]

            metadata_dict = {
                example_utils.SATELLITE_TIME_DIM:
                    numpy.array([valid_time_unix_sec], dtype=int),
                example_utils.SATELLITE_PREDICTOR_UNGRIDDED_DIM:
                    validation_option_dict[neural_net.SATELLITE_PREDICTORS_KEY]
            }

            these_dim_2d = (
                example_utils.SATELLITE_TIME_DIM,
                example_utils.SATELLITE_PREDICTOR_UNGRIDDED_DIM
            )
            main_data_dict = {
                example_utils.SATELLITE_PREDICTORS_UNGRIDDED_KEY: (
                    these_dim_2d,
                    numpy.expand_dims(predictor_matrices[1][i, j, :], axis=0)
                ),
                satellite_utils.CYCLONE_ID_KEY: (
                    (example_utils.SATELLITE_TIME_DIM,),
                    [cyclone_id_string]
                )
            }

            this_table_xarray = xarray.Dataset(
                data_vars=main_data_dict, coords=metadata_dict
            )
            panel_file_names[j] = (
                plot_scalar_satellite.plot_predictors_one_time(
                    example_table_xarray=this_table_xarray, time_index=0,
                    predictor_indices=predictor_indices,
                    output_dir_name=output_dir_name,
                    info_string=(
                        info_strings[i] if lag_times_sec[j] == 0 else None
                    )
                )
            )
            imagemagick_utils.resize_image(
                input_file_name=panel_file_names[j],
                output_file_name=panel_file_names[j],
                output_size_pixels=PANEL_SIZE_PX
            )

        concat_figure_file_name = '{0:s}/{1:s}_scalar_satellite.jpg'.format(
            output_dir_name,
            time_conversion.unix_sec_to_string(
                init_times_unix_sec[i], TIME_FORMAT
            )
        )
        _concat_panels(
            panel_file_names=panel_file_names,
            concat_figure_file_name=concat_figure_file_name
        )


def _plot_lagged_ships_predictors(
        example_table_xarray, model_metadata_dict, predictor_matrices,
        init_times_unix_sec, info_strings, output_dir_name):
    """Plots lagged SHIPS predictors for each init time and model lag time.

    :param example_table_xarray: See doc for `_plot_brightness_temps`.
    :param model_metadata_dict: Same.
    :param predictor_matrices: Same.
    :param init_times_unix_sec: Same.
    :param info_strings: Same.
    :param output_dir_name: Same.
    """

    # Housekeeping.
    xt = example_table_xarray
    validation_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )

    num_init_times = len(init_times_unix_sec)
    model_lag_times_sec = (
        HOURS_TO_SECONDS *
        validation_option_dict[neural_net.SHIPS_LAG_TIMES_KEY]
    )
    num_model_lag_times = len(model_lag_times_sec)

    predictor_names = (
        validation_option_dict[neural_net.SHIPS_PREDICTORS_LAGGED_KEY]
    )
    builtin_lag_times_hours = xt.coords[example_utils.SHIPS_LAG_TIME_DIM].values
    num_predictors = len(predictor_names)
    num_builtin_lag_times = len(builtin_lag_times_hours)
    predictor_indices = numpy.linspace(
        0, num_predictors - 1, num=num_predictors, dtype=int
    )

    # Do actual stuff (plot 2-D colour maps with normalized predictors).
    for i in range(num_init_times):
        panel_file_names = [''] * num_model_lag_times

        for j in range(num_model_lag_times):
            valid_time_unix_sec = (
                init_times_unix_sec[i] - model_lag_times_sec[j]
            )
            cyclone_id_string = xt[satellite_utils.CYCLONE_ID_KEY].values[0]

            metadata_dict = {
                example_utils.SHIPS_LAG_TIME_DIM: builtin_lag_times_hours,
                example_utils.SHIPS_VALID_TIME_DIM:
                    numpy.array([valid_time_unix_sec], dtype=int),
                example_utils.SHIPS_PREDICTOR_LAGGED_DIM: predictor_names
            }

            predictor_matrix = predictor_matrices[2][
                i, j, :(num_predictors * num_builtin_lag_times)
            ]
            predictor_matrix = numpy.reshape(
                predictor_matrix, (num_builtin_lag_times, num_predictors),
                order='F'
            )
            predictor_matrix = numpy.expand_dims(predictor_matrix, axis=0)

            these_dim_3d = (
                example_utils.SHIPS_VALID_TIME_DIM,
                example_utils.SHIPS_LAG_TIME_DIM,
                example_utils.SHIPS_PREDICTOR_LAGGED_DIM
            )
            main_data_dict = {
                example_utils.SHIPS_PREDICTORS_LAGGED_KEY: (
                    these_dim_3d, predictor_matrix
                ),
                ships_io.CYCLONE_ID_KEY: (
                    (example_utils.SHIPS_VALID_TIME_DIM,),
                    [cyclone_id_string]
                )
            }

            this_table_xarray = xarray.Dataset(
                data_vars=main_data_dict, coords=metadata_dict
            )
            panel_file_names[j] = (
                plot_ships.plot_lagged_predictors_one_init_time(
                    example_table_xarray=this_table_xarray, init_time_index=0,
                    predictor_indices=predictor_indices,
                    output_dir_name=output_dir_name,
                    info_string=(
                        info_strings[i] if model_lag_times_sec[j] == 0 else None
                    )
                )
            )
            imagemagick_utils.resize_image(
                input_file_name=panel_file_names[j],
                output_file_name=panel_file_names[j],
                output_size_pixels=PANEL_SIZE_PX
            )

        concat_figure_file_name = '{0:s}/{1:s}_ships_lagged.jpg'.format(
            output_dir_name,
            time_conversion.unix_sec_to_string(
                init_times_unix_sec[i], TIME_FORMAT
            )
        )
        _concat_panels(
            panel_file_names=panel_file_names,
            concat_figure_file_name=concat_figure_file_name
        )


def _plot_forecast_ships_predictors(
        example_table_xarray, model_metadata_dict, predictor_matrices,
        init_times_unix_sec, info_strings, output_dir_name):
    """Plots lagged SHIPS predictors for each init time and lag time.

    :param example_table_xarray: See doc for `_plot_brightness_temps`.
    :param model_metadata_dict: Same.
    :param predictor_matrices: Same.
    :param init_times_unix_sec: Same.
    :param info_strings: Same.
    :param output_dir_name: Same.
    """

    # Housekeeping.
    xt = example_table_xarray
    validation_option_dict = (
        model_metadata_dict[neural_net.VALIDATION_OPTIONS_KEY]
    )

    num_init_times = len(init_times_unix_sec)
    model_lag_times_sec = (
        HOURS_TO_SECONDS *
        validation_option_dict[neural_net.SHIPS_LAG_TIMES_KEY]
    )
    num_model_lag_times = len(model_lag_times_sec)

    predictor_names = (
        validation_option_dict[neural_net.SHIPS_PREDICTORS_FORECAST_KEY]
    )
    forecast_hours = xt.coords[example_utils.SHIPS_FORECAST_HOUR_DIM].values
    num_predictors = len(predictor_names)
    num_forecast_hours = len(forecast_hours)
    predictor_indices = numpy.linspace(
        0, num_predictors - 1, num=num_predictors, dtype=int
    )

    # Do actual stuff (plot 2-D colour maps with normalized predictors).
    for i in range(num_init_times):
        panel_file_names = [''] * num_model_lag_times

        for j in range(num_model_lag_times):
            valid_time_unix_sec = (
                init_times_unix_sec[i] - model_lag_times_sec[j]
            )
            cyclone_id_string = xt[satellite_utils.CYCLONE_ID_KEY].values[0]

            metadata_dict = {
                example_utils.SHIPS_FORECAST_HOUR_DIM: forecast_hours,
                example_utils.SHIPS_VALID_TIME_DIM:
                    numpy.array([valid_time_unix_sec], dtype=int),
                example_utils.SHIPS_PREDICTOR_FORECAST_DIM:
                    predictor_names
            }

            predictor_matrix = predictor_matrices[2][
                i, j, (-num_predictors * num_forecast_hours):
            ]
            predictor_matrix = numpy.reshape(
                predictor_matrix, (num_forecast_hours, num_predictors),
                order='F'
            )
            predictor_matrix = numpy.expand_dims(predictor_matrix, axis=0)

            these_dim_3d = (
                example_utils.SHIPS_VALID_TIME_DIM,
                example_utils.SHIPS_FORECAST_HOUR_DIM,
                example_utils.SHIPS_PREDICTOR_FORECAST_DIM
            )
            main_data_dict = {
                example_utils.SHIPS_PREDICTORS_FORECAST_KEY: (
                    these_dim_3d, predictor_matrix
                ),
                ships_io.CYCLONE_ID_KEY: (
                    (example_utils.SHIPS_VALID_TIME_DIM,),
                    [cyclone_id_string]
                )
            }

            this_table_xarray = xarray.Dataset(
                data_vars=main_data_dict, coords=metadata_dict
            )
            panel_file_names[j] = (
                plot_ships.plot_fcst_predictors_one_init_time(
                    example_table_xarray=this_table_xarray, init_time_index=0,
                    predictor_indices=predictor_indices,
                    output_dir_name=output_dir_name,
                    info_string=(
                        info_strings[i] if model_lag_times_sec[j] == 0 else None
                    )
                )
            )
            imagemagick_utils.resize_image(
                input_file_name=panel_file_names[j],
                output_file_name=panel_file_names[j],
                output_size_pixels=PANEL_SIZE_PX
            )

        concat_figure_file_name = '{0:s}/{1:s}_ships_forecast.jpg'.format(
            output_dir_name,
            time_conversion.unix_sec_to_string(
                init_times_unix_sec[i], TIME_FORMAT
            )
        )
        _concat_panels(
            panel_file_names=panel_file_names,
            concat_figure_file_name=concat_figure_file_name
        )


def _run(model_metafile_name, norm_example_file_name, normalization_file_name,
         prediction_file_name, init_time_strings, first_init_time_string,
         last_init_time_string, output_dir_name):
    """Plots all predictors (scalars and brightness temps) for a given model.

    This is effectively the main method.

    :param model_metafile_name: See documentation at top of file.
    :param norm_example_file_name: Same.
    :param normalization_file_name: Same.
    :param prediction_file_name: Same.
    :param init_time_strings: Same.
    :param first_init_time_string: Same.
    :param last_init_time_string: Same.
    :param output_dir_name: Same.
    """

    file_system_utils.mkdir_recursive_if_necessary(
        directory_name=output_dir_name
    )

    print('Reading metadata from: "{0:s}"...'.format(model_metafile_name))
    model_metadata_dict = neural_net.read_metafile(model_metafile_name)
    validation_option_dict = model_metadata_dict[
        neural_net.VALIDATION_OPTIONS_KEY
    ]
    validation_option_dict[neural_net.EXAMPLE_FILE_KEY] = norm_example_file_name

    print('Reading data from: "{0:s}"...'.format(norm_example_file_name))
    example_table_xarray = example_io.read_file(norm_example_file_name)
    cyclone_id_string = (
        example_table_xarray[satellite_utils.CYCLONE_ID_KEY].values[0]
    )
    if not isinstance(cyclone_id_string, str):
        cyclone_id_string = cyclone_id_string.decode('utf-8')

    print('Reading data from: "{0:s}"...'.format(normalization_file_name))
    normalization_table_xarray = normalization.read_file(
        normalization_file_name
    )

    border_latitudes_deg_n, border_longitudes_deg_e = border_io.read_file()
    print(SEPARATOR_STRING)

    data_dict = neural_net.create_inputs(validation_option_dict)
    predictor_matrices = data_dict[neural_net.PREDICTOR_MATRICES_KEY]
    all_init_times_unix_sec = data_dict[neural_net.INIT_TIMES_KEY]
    print(SEPARATOR_STRING)

    if len(init_time_strings) == 1 and init_time_strings[0] == '':
        first_init_time_unix_sec = time_conversion.string_to_unix_sec(
            first_init_time_string, TIME_FORMAT
        )
        last_init_time_unix_sec = time_conversion.string_to_unix_sec(
            last_init_time_string, TIME_FORMAT
        )
        time_indices = general_utils.find_exact_times(
            actual_times_unix_sec=all_init_times_unix_sec,
            first_desired_time_unix_sec=first_init_time_unix_sec,
            last_desired_time_unix_sec=last_init_time_unix_sec
        )
    else:
        init_times_unix_sec = numpy.array([
            time_conversion.string_to_unix_sec(t, TIME_FORMAT)
            for t in init_time_strings
        ], dtype=int)

        time_indices = general_utils.find_exact_times(
            actual_times_unix_sec=all_init_times_unix_sec,
            desired_times_unix_sec=init_times_unix_sec
        )

    predictor_matrices = [a[time_indices, ...] for a in predictor_matrices]
    init_times_unix_sec = all_init_times_unix_sec[time_indices]

    sort_indices = numpy.argsort(init_times_unix_sec)
    predictor_matrices = [a[sort_indices, ...] for a in predictor_matrices]
    init_times_unix_sec = init_times_unix_sec[sort_indices]

    current_intensities_kt, future_intensities_kt = _get_intensities(
        example_table_xarray=example_table_xarray,
        init_times_unix_sec=init_times_unix_sec,
        model_metadata_dict=model_metadata_dict
    )

    num_init_times = len(init_times_unix_sec)
    info_strings = [''] * num_init_times

    for i in range(num_init_times):
        info_strings[i] = 'I = {0:d} to {1:d} kt'.format(
            current_intensities_kt[i], future_intensities_kt[i]
        )

    if prediction_file_name != '':
        forecast_prob_matrix, target_classes = _get_predictions_and_targets(
            prediction_file_name=prediction_file_name,
            cyclone_id_string=cyclone_id_string,
            init_times_unix_sec=init_times_unix_sec
        )

        for i in range(num_init_times):
            info_strings[i] += (
                '; class = {0:d} of {1:d}; prob = {2:.2f}'
            ).format(
                target_classes[i] + 1, forecast_prob_matrix.shape[1],
                forecast_prob_matrix[i, target_classes[i]]
            )

    _plot_brightness_temps(
        example_table_xarray=example_table_xarray,
        normalization_table_xarray=normalization_table_xarray,
        model_metadata_dict=model_metadata_dict,
        predictor_matrices=predictor_matrices,
        info_strings=info_strings,
        init_times_unix_sec=init_times_unix_sec,
        border_latitudes_deg_n=border_latitudes_deg_n,
        border_longitudes_deg_e=border_longitudes_deg_e,
        output_dir_name=output_dir_name
    )
    print(SEPARATOR_STRING)

    _plot_scalar_satellite_predictors(
        example_table_xarray=example_table_xarray,
        model_metadata_dict=model_metadata_dict,
        predictor_matrices=predictor_matrices,
        info_strings=info_strings,
        init_times_unix_sec=init_times_unix_sec,
        output_dir_name=output_dir_name
    )
    print(SEPARATOR_STRING)

    _plot_lagged_ships_predictors(
        example_table_xarray=example_table_xarray,
        model_metadata_dict=model_metadata_dict,
        predictor_matrices=predictor_matrices,
        info_strings=info_strings,
        init_times_unix_sec=init_times_unix_sec,
        output_dir_name=output_dir_name
    )
    print(SEPARATOR_STRING)

    _plot_forecast_ships_predictors(
        example_table_xarray=example_table_xarray,
        model_metadata_dict=model_metadata_dict,
        predictor_matrices=predictor_matrices,
        info_strings=info_strings,
        init_times_unix_sec=init_times_unix_sec,
        output_dir_name=output_dir_name
    )


if __name__ == '__main__':
    INPUT_ARG_OBJECT = INPUT_ARG_PARSER.parse_args()

    _run(
        model_metafile_name=getattr(INPUT_ARG_OBJECT, MODEL_METAFILE_ARG_NAME),
        norm_example_file_name=getattr(INPUT_ARG_OBJECT, EXAMPLE_FILE_ARG_NAME),
        normalization_file_name=getattr(
            INPUT_ARG_OBJECT, NORMALIZATION_FILE_ARG_NAME
        ),
        prediction_file_name=getattr(
            INPUT_ARG_OBJECT, PREDICTION_FILE_ARG_NAME
        ),
        init_time_strings=getattr(INPUT_ARG_OBJECT, INIT_TIMES_ARG_NAME),
        first_init_time_string=getattr(INPUT_ARG_OBJECT, FIRST_TIME_ARG_NAME),
        last_init_time_string=getattr(INPUT_ARG_OBJECT, LAST_TIME_ARG_NAME),
        output_dir_name=getattr(INPUT_ARG_OBJECT, OUTPUT_DIR_ARG_NAME)
    )
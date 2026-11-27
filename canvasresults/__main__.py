import argparse
import logging

from .canvasresults import CanvasResults


class LogLevelAction(argparse.Action):
    """
    ArgParse action type for a CLI argument - intended to be used to set/increase the logging/debug level. The variable should start with a default of
    ``log.WARNING``. Everytime the variable is provided it increases to ``log.INFO``, then ``log.DEBUG``

    NOTE: This class is designed to be used for actioning a flag-type parameter in the context of command-line argument parsing. When executed due to
    specification on the command line, the parameter name is set/modified as per above
    """
    def __call__(self, parser, namespace, values, option_string=None):
        """
        Called when parameter/flag has been specified.

        No validation, retrieve the current parameter value (with default ``log.WARNING`` if it does not yet exist). Then use a look-up table to increase the
        log level to the next value, capping at a maximum value of ``log.DEBUG``. Save the updated value back to the ``namespace``

        :param parser: ArgParse instance, used to send errors back to the parser.
        :param namespace: Current parsed parameters.
        :param values: Current option being parsed.
        :param option_string: Actual option (e.g. --hint)
        """
        # Get the current log level stored in self.dest. If not set, return logging.WARNING
        level = getattr(namespace, self.dest, logging.WARNING)

        # Maps the next logging level to choose based on the current logging level. Each level maps to the next, logging.DEBUG is the max level so maps to itself
        next_level_map: dict[int, int] = {logging.WARNING: logging.INFO, logging.INFO: logging.DEBUG, logging.DEBUG: logging.DEBUG}

        # Set the stored logging level to the next one
        setattr(namespace, self.dest, next_level_map[level])


def parse_arguments() -> argparse.Namespace:
    """
    Parses and returns the command-line arguments for the CanvasResults library test

    :returns: argparse.Namespace: A Namespace object containing the parsed command line arguments
    :raises: foo: This function will raise errors related to incorrect command-line argument parsing using argparse.ArgumentParser
    """
    _BOLD_MAGENTA = "\033[1;35m"
    """ASCII code for Bold Magenta - used to format strings in argparse output"""
    _BOLD_CYAN = "\033[1;36m"
    """ASCII code for Bold Cyan - used to format strings in argparse output"""
    _ITALIC = "\033[3m"
    """ASCII code for Italic - used to format strings in argparse output"""
    _RESET = "\033[0m"

    parser = argparse.ArgumentParser(description='CanvasResults Module Testing', formatter_class=argparse.RawTextHelpFormatter, allow_abbrev=False)

    parser.add_argument('-u', '--url', default='https://swinburne.instructure.com', help='Canvas URL (default: %(default)s)')
    parser.add_argument('-t', '--token', required=True, help='Canvas API token')
    parser.add_argument('-c', '--course', required=True, help="Canvas course name")
    parser.add_argument('-a', '--assignment', nargs="+", required=True, help="One or more Canvas assignment names")
    parser.add_argument('-v', '--verbose', dest='log_level', nargs=0, action=LogLevelAction, default=logging.WARNING,
                        help=f'Verbose mode. Causes {_BOLD_MAGENTA}%(prog)s{_RESET} to print debugging messages while running. Multiple -v options increase the verbosity.  The maximum is 2.')

    return parser.parse_args()


def test_module(arguments: argparse.Namespace) -> None:
    logging.basicConfig(format='%(levelname)-8s %(name)-30s %(funcName)-20s %(message)-60s')

    log = logging.getLogger(__package__)
    log.setLevel(arguments.log_level)

    print('\n── Connecting to Canvas ────────────────────────────────────────────────────')
    canvas = CanvasResults(canvas_url=arguments.url, token=arguments.token)

    print('\n── Finding Canvas Course ───────────────────────────────────────────────────')
    for progress in canvas.find_courses(arguments.course): log.debug(f'Matching Course: {progress['course_name']}')

    log.info(f'Selecting most recent offering of Course')
    canvas.set_course(canvas.courses[0])

    print('\n── Finding Course Assignments ──────────────────────────────────────────────')
    for progress in canvas.find_assignments(): log.debug(f'Found Assignment: {progress["assignment_name"]}')

    print('\n── Validating Canvas Assignments ───────────────────────────────────────────')
    canvas.validate_assignments(assignment_names=arguments.assignment)

    print('\n── Downloading Student Details ─────────────────────────────────────────────')
    canvas.select_students()

    # return
    print('\n── Downloading Gradebook ───────────────────────────────────────────────────')
    for result in canvas.download_gradebook(assignment_names=arguments.assignment):
        print(f'\r\033[2KDownloading: {result['percentage']:6.2%}% ({result['count']}/{result['total']}) {result['student_id']} - {result['assignment_name']}', end='', flush=True)

    print()

    print('\n── Displaying Gradebook ────────────────────────────────────────────────────')
    assignments = list(next(iter(canvas.gradebook.values())).keys())

    print(f"{'Student ID':<12}", end="")
    for assignment in assignments:
        print(f"{assignment:^20}", end="")
    print()

    for student_id, grades in canvas.gradebook.items():
        print(f"{student_id:<12}", end="")
        for assignment in assignments:
            print(f"{grades.get(assignment, '')!s:^20}", end="")
        print()


if __name__ == "__main__":
    print('Testing CanvasResults...')
    try:
        arguments = parse_arguments()
        test_module(arguments)
    except Exception as e:
        print(f'\nERROR [{type(e).__name__}]: {e}')

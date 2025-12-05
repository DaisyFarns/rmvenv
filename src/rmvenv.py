#!/bin/python3

import os
import re
import sys
import math
import shutil
import tomllib
import argparse
import functools
import threading

VERSION = "0.3.0"

SIZES = {
    "k": 2 ** 10,
    "m": 2 ** 20,
    "g": 2 ** 30,
    "t": 2 ** 40
}

def is_list_of_strings(value) -> bool:
    """Return True if the type is a list containing strings, if anything"""
    # return type(value) is not list or not functools.reduce(lambda x: type(x) is str, value, True)

    if type(value) is not list:
        return False

    if not functools.reduce(lambda x, y: x and type(y) is str, value, True):
        return False

    return True

def handle_re_error(error: re.error):
    print("rmvenv: Regex error in " + fr"'{error.pattern}':", file=sys.stderr)
    print(error, file=sys.stderr)
    print(
        "Were raw strings surrounded by ' characters "
        "used in the TOML file?",
        file=sys.stderr
    )
    sys.exit(78)

class ConfigLoader:
    """
    Load configuration file
    """

    # Relative to the this script
    RELATIVE_DEFAULT_CONFIG_PATH = os.path.join("data", "default_config.toml")

    # Relative to the HOME directory
    RELATIVE_CONFIG_PATH = os.path.join(".config", "rmvenv_config.toml")

    
    def __init__(self):
        self.config_path = ""
        self.ignored: re.Pattern
        self.marked_files: list[re.Pattern] = []
        self.default_file_size: str
        self.projects: dict[re.Pattern, re.Pattern] = {}

        self.find_config()
        self.load_config()

    def find_config(self):
        """Find the configuration file in .config/rmvenv_config.toml"""
        home_dir = os.environ["HOME"]
        expected_config_path = os.path.join(home_dir, self.RELATIVE_CONFIG_PATH)

        if not os.path.exists(expected_config_path):
            home_config_path = os.path.dirname(self.RELATIVE_CONFIG_PATH)
            if not os.path.exists(home_config_path):
                os.mkdir(home_config_path)

            this_script_dir_path = os.path.dirname(os.path.abspath(__file__))
            default_config_path = os.path.join(
                this_script_dir_path, self.RELATIVE_DEFAULT_CONFIG_PATH
            )

            shutil.copy(default_config_path, expected_config_path)
            print(
                f"note: Created default config file at {expected_config_path}",
                file=sys.stderr
            )

        self.config_path = expected_config_path
        
    def load_config(self):
        try:
            with open(self.config_path, "rb") as file:
                toml_file = tomllib.load(file)

        except FileNotFoundError:
            print(
                  f"rmvenv: Couldn't find config file at: {self.config_path}",
                  file=sys.stderr
              )
            sys.exit(1)

        except PermissionError as e:
            print(
                "rmvenv: Couldn't open config file ({}): {}".format(
                    self.config_path, e
                ),
                file=sys.stderr
            )
            sys.exit(77)

        except tomllib.TOMLDecodeError as e:
            print(
                f"rmvenv: Couldn't parse config file {self.config_path}:",
                file=sys.stderr
            )
            print(e, file=sys.stderr)
            sys.exit(1)

        # Load and check key types

        expected_keys = ["ignored", "default_max_size", "marked_files"]

        unknown_keys = []

        try:
            for key, value in toml_file.items():
                
                if key in expected_keys:

                    expected_keys.remove(key)

                    # A list of regexes of a directory name that are never
                    # explored during search, expect for size calculation
                    if key == "ignored":

                        # Check type is a list, and that it only contains
                        # strings if anything
                        if not is_list_of_strings(value):
                            raise TypeError(
                                "'ignored' key must be a list of regex strings"
                            )

                        self.ignored = [re.compile(r) for r in value]

                    # The default size of a file or directory to be marked if
                    # marking directories for size
                    elif key == "default_max_size":
                        if type(value) is not str:
                            raise TypeError(
                                "'default_max_size' key must be a string "
                                "of a filesize"
                            )

                        value = value.strip()
                            
                        if not re.match(
                            r"^\d+[kmgt]?$",
                            value,
                            flags=re.IGNORECASE
                        ):
                            raise ValueError(
                                "Can't interpret {} "
                                "(default_max_size) as a filesize. "
                                "Use '2048', '50M', etc"
                                .format(repr(value))
                            )

                        self.default_file_size = value

                    # A list of regex of filenames to always mark
                    elif key == "marked_files":
                        if not is_list_of_strings(value):
                            raise TypeError(
                                "'marked_files' must be a list of regex strings"
                            )

                        self.marked_files = [re.compile(r) for r in value]

                    else:
                        # logic error
                        raise NotImplementedError(
                            "Expected a known key but wasn't tested. "
                        )

                else:
                    unknown_keys.append(key)

            # Check that all keys were used and no unknown keys are used
         
            if "project" in unknown_keys:
                unknown_keys.remove("project")  # Special key that will be
                                                # handled later
        
            if len(expected_keys) > 0 or len(unknown_keys) > 0:
                print("rmvenv: Configuration error:", file=sys.stderr)
                if len(expected_keys) > 0:
                    print(
                        "The following keys are missing from the config file:",
                        file=sys.stderr
                    )
                    print(f"\t{expected_keys}", file=sys.stderr)
                if len(unknown_keys):
                    print(
                        "The following keys from the config file are unknown:",
                        file=sys.stderr
                    )
                    print(f"\t{unknown_keys}", file=sys.stderr)

                sys.exit(1)

            if "project" in toml_file:

                # Verify that "project" table is a directory of strings as keys,
                # who's values are a dictionary containing the keys 'marker' and
                # 'marked' which are a single string or a regular expression

                projects: dict = toml_file["project"]

                if type(projects) is not dict:
                    raise TypeError("'project' must be a table or dictionary")

                for key, value in projects.items():

                    # `value` should be a dictionary containing two keys
                    if type(value) is not dict:
                        raise TypeError(
                            "project '{}' must be a table or dictionary"
                            .format(rf"{key}")
                        )

                    if "marker" not in value or "marked" not in value:
                        raise TypeError(
                            "project '{}' must contain the keys 'marker' and 'marked' as strings"
                            .format(rf"{key}")
                        )

                    for regex_key in ["marker", "marked"]:
                        if type(value[regex_key]) is not str:
                            raise TypeError(
                                "Type of the value for the '{}' in project "
                                "'{}' must be a string"
                                .format(regex_key, fr"{key}")
                            )

                    for regex_key in value:
                        if regex_key not in ["marker", "marked"]:
                            raise ValueError(
                                f"key {repr(regex_key)} in "
                                "project.{key} unknown.\n"
                                "Must be one of 'marker' or 'marked'"
                            )

                self.set_project_regexes(projects)

        except TypeError as e:
            print("rmvenv: Configuration type error:", file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(78)

        except ValueError as e:
            print("rmvenv: Configuration value error:", file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(78)

        except re.error as e:
            handle_re_error(e)

    def set_project_regexes(self, project_info):
        """
        Take input of the project table, and add it to the self.projects dict.
        Types must have already been validated before this function call.

        Raises re.error during regex compilation. 
        """

        for project_name in project_info:
            self.projects[
                re.compile(project_info[project_name]["marker"])
            ] = re.compile(project_info[project_name]["marked"])
        
# TODO Modify code to use new config, including printing where

config = ConfigLoader()

# This class can just be printed
class HumanFilesize:
    SIG_FIGS = 3

    def __init__(self, size_bytes):
        """ Get a human readable representation in bytes """
        self.size_bytes = size_bytes
        self.size_human_string = ""

        self.__load_string()

    def __load_string(self):
        """ Load the size_human_string"""
        suffixes = list(SIZES.keys())
        suffixes.sort(key=SIZES.get, reverse=True)

        suffixes

        suffix = ""
        for s in suffixes:
            if SIZES[s] <= self.size_bytes:
                suffix = s
                break
        if suffix:
            value = self.size_bytes / SIZES[s]

            # Round to number of sig figs

            value_magnitude = math.floor(math.log10(value))
            round_number = self.SIG_FIGS - value_magnitude - 1
            value = round(value, round_number)

            value_str = str(value).strip("0").strip(".")
            value_str += " " + suffix.upper() + "b"
        else:
            value_str = str(self.size_bytes) + " bytes"

        self.size_human_string = value_str

    def str(self):
        return self.__str__()

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return self.size_human_string


class StatusIndicator:

    # Don't Log anything before this time
    DONT_LOG = 0.1

    # Don't print what files are being written before this time
    LOG_WORKING = 0.5

    # Print every x seconds
    LOG_PERIOD = 0.3

    # File to write logs to
    FILE = sys.stderr

    def __init__(self):
        self.thread: threading.Thread = threading.Thread(
            target=self.main_thread
        )
        self.text: str = ""
        self.text_lock = threading.Lock()
        self.stop_flag = threading.Event()

        self.non_interactive_terminal = False

        try:
            self.terminal_width = os.get_terminal_size().columns
        except OSError as e:
            if e.errno == 25:
                # Non interactive terminal
                self.non_interactive_terminal = True

    def update_text(self, text):
        """
        Updates the status. Acquires the lock on the text
        """

        self.text_lock.acquire()
        self.text = text
        self.text_lock.release()

        # print("New text:", text)

    def main_thread(self):
        """Displays error info. Should run in a thread"""

        # If non interactive terminal, stop immediately
        if self.non_interactive_terminal:
            return

        if self.stop_flag.wait(self.DONT_LOG):
            return

        self.__write("Working")

        if self.stop_flag.wait(self.LOG_WORKING - self.DONT_LOG):
            self.__write("")  # Clear the screen
            return

        while True:

            # Write text to screen, including a carriage return '\r'

            self.text_lock.acquire()

            # If required to stop after getting lock
            if self.stop_flag.is_set():
                self.text_lock.release()
                return

            self.__write(f"Working: {self.text}")

            self.text_lock.release()

            # Wait the log period before printing again

            if self.stop_flag.wait(self.LOG_PERIOD):
                self.__write(" " * self.terminal_width)
                return

    def __write(self, text):
        """
        Write text to terminal, ending in a carriage return.

        Truncates the text with ' ...' if it's to long
        """

        if len(text) > self.terminal_width:
            text = text[:self.terminal_width - 4] + " ..."

        white_space = self.terminal_width - len(text)
        text = text + " " * white_space

        self.FILE.write(text + "\r")

    def clear(self):
        """ Clear the line of text """
        self.__write("")

    def start(self):
        """
        Start the thread
        """
        self.thread.start()

    def stop(self):
        """Stop the thread"""
        self.stop_flag.set()

        # Wait for thread to finish
        self.thread.join()


class SizeAction(argparse.Action):
    """
    Class for an optional argument.

    Stores the value "None" if argument is missing

    Stores a default value if argument is present, but no value is given

    Stores the given value if value is given for argument
    """

    def __call__(self, parser, namespace, values, option_string=None):

        if values is None:
            size_string = config.default_file_size
        else:
            size_string = values

        setattr(
            namespace,
            self.dest,
            self.get_file_size_from_string(size_string)
        )

    def get_file_size_from_string(self, string: str) -> int:

        string = string.lower()

        suffix_multiplier = 1

        # Check for file size suffix

        for suffix in SIZES:
            if string.endswith(suffix):
                suffix_multiplier = SIZES[suffix]

                # Remove the suffix from the string
                string = string[:-1]

        try:
            # Raises exception if string can't be parsed as a float
            size = float(string)
        except ValueError:
            print(
                f"Can't interpret {string.__repr__()} as file size",
                file=sys.stderr
            )
            print(
                "Use sizes like '100m', '500k', '2G'...",
                file=sys.stderr
            )
            sys.exit(1)

        return (size * suffix_multiplier).__floor__()


class Cleaner:
    def __init__(self):

        # Don't follow symlinks by default
        self.follow_symlinks = False

        # os.DirEntry of marked items to print / delete
        self.marked_items: set[os.DirEntry] = set()

        # Check for large files. By default, False
        self.check_size = False

        # Number of bytes a file or dir needs to be marked due to size
        self.mark_size_bytes = 0

        # Dictionary which stores the sizes of items in bytes. The size of
        # a directory is the sum of the size of the files and directory
        # within it.
        self.sizes = {}

        # Sub directories of directories
        self.children = {}

        # Never ask for user input
        self.force = False

        # Flag to delete marked items instead of printing them
        self.delete_marked_items = False

        # Status indicator in the terminal
        self.status = StatusIndicator()

    def get_size(self, item: os.DirEntry | str):
        """
        Gets the size of a file or a directory.

        If run on a directory wholes size hasn't been evaluated before,
        takes a long time!

        Sizes are stored when calling this function so that finding the
        size of a subdirectory or file within called directory takes O(1)
        time.

        After calling this print(f"Would delete {item.path} ...") function on a
        directory, all subdirectories
        and files in the directory will be stored as well as their sizes
        """

        if type(item) is str:
            item_path = item
            is_item_file = (not os.path.islink(item)) and os.path.isfile(item)
        else:
            item_path = item.path
            is_item_file = item.is_file(follow_symlinks=False)

        if "DENIED" in item_path:
            pass

        # If size already known, return it
        if item_path in self.sizes:
            self.status.update_text(item_path)
            return self.sizes[item_path]

        try:
            if type(item) is str:
                item_stat = os.stat(item)
                is_item_dir = os.path.isdir(item) and (not os.path.islink(item))
            else:
                item_stat = item.stat()
                is_item_dir = item.is_dir(follow_symlinks=False)
        except FileNotFoundError:
            # If the file isn't found for whatever reason, then it can't be
            # stated or have any size, so return zero
            return 0

        if is_item_file:
            size = item_stat.st_size
            self.sizes[item_path] = size

            self.status.update_text(item_path)
            return size

        elif is_item_dir:
            # Get children of directory

            if item not in self.children:
                self.children[item] = list(os.scandir(item.path))

            size = item_stat.st_size
            for child_item in self.children[item]:
                size += self.get_size(child_item)

            self.sizes[item_path] = size

            self.status.update_text(item_path)

            return size

        else:
            # Not a file or directory, or something with can read. Skip.
            return 0

    def evaluate(self, item: os.DirEntry | str) -> bool:
        """
        Evaluates a DirEntry object to deicide if it should be marked
        Will mark children of dir entries if able.
        """

        if item in self.marked_items:
            return True

        if type(item) is str:
            is_item_symlink = os.path.islink(item)
        else:
            is_item_symlink = os.path.islink(item.path)

        if not self.follow_symlinks and is_item_symlink:
            return False

        if type(item) is str:
            is_item_file = os.path.isfile(item)
            is_item_dir = os.path.isdir(item)
            item_name = os.path.basename(item)
        else:
            is_item_file = item.is_file()
            is_item_dir = item.is_dir()
            item_name = item.name

        if is_item_file:
            if any(
                   [
                       pattern.search(item_name) for
                       pattern in config.marked_files
                   ]
               ):

                return True

        elif is_item_dir:
            if item not in self.children:
                self.children[item] = list(os.scandir(item))

            child_paths = [child.path for child in self.children[item]]

            for (marker_re, marked_re) in config.projects.items():

                # If this directory contains a file showing we need to
                # mark something...
                if any(
                       [
                           marker_re.search(os.path.basename(child_path))
                           for child_path in child_paths
                       ]
                ):

                    # Find any children to mark

                    for child in self.children[item]:
                        if marked_re.search(child.name):
                            self.marked_items.add(child.path)

        if self.check_size and self.evaluate_size(item):
            return True

        return False

    def evaluate_size(self, item: os.DirEntry | str) -> bool:
        """
        Evaluates the size of the item, and if it needs to be marked
        because of this.

        If item is a directory, can take a long time!
        """

        if type(item) is str:
            is_item_symlink = os.path.islink(item)
            is_item_file = os.path.isfile(item)
            is_item_dir = os.path.isdir(item)
        else:
            is_item_symlink = item.is_symlink()
            is_item_file = item.is_file()
            is_item_dir = item.is_dir()
            
        # Calculate the size of the item
        size = self.get_size(item)

        if size < self.mark_size_bytes:
            return False

        if self.follow_symlinks and is_item_symlink:
            return False

        if is_item_file:
            return True

        if is_item_dir:

            # Only mark a directory if it's above the size limit AND none
            # of it's children are above the size limit

            children = self.children[item]
            children_sizes = [
                self.get_size(child) for child in children
            ]

            if max(children_sizes) < self.mark_size_bytes:
                return True

        return False

    def search(self, path):
        """
        Print build directors and files recursively starting from path
        """

        # Get items in directory
        items = list(os.scandir(path))
        items.sort(key=lambda x: x.name)

        for item in items:

            # Skip all symlinks
            if item.is_symlink():
                continue

            try:
                if item.path in self.marked_items:
                    continue

                # Check if you should mark it
                if self.evaluate(item):
                    self.marked_items.add(item.path)

                else:
                    if (
                        item.is_dir() and

                        # and the dir name doesn't match any patterns of ignore
                        # in the config
                        not any(
                                [pattern.search(item.name)
                                    for pattern in config.ignored]
                            )
                    ):

                        if item.path in self.marked_items:
                            print("---------------- Continue -----------")
                            continue

                        # Search recursively
                        self.search(item.path)

            except PermissionError:
                # Don't have permission to read file

                # Manage the status, as this is printed to stderr
                with self.status.text_lock:
                    self.status.clear()

                    # Print error information
                    print(
                        f"Read permission error: {item.path}",
                        file=sys.stderr
                    )

                # Release the lock, allowing the status to continue

            self.status.update_text(item.path)

            # Delete unneeded items
            if item in self.children:
                del self.children[item]

    def delete_marked_item(self, item_path) -> bool:
        """
        Ask the user to delete an item, deleting if requested

        Deletes subdirectories

        :param item: os.DirEntry item to delete
        :returns: A boolean of if the item got deleted
        """

        if not self.force:
            if item_path in self.sizes:
                size_str = HumanFilesize(self.sizes[item_path]).str()
            else:
                size_str = ""

            prompt_string = f"Remove {item_path}?"
            if size_str:
                prompt_string += f" ({size_str})"

            prompt_string += " (y/n) > "

            user_input = input(prompt_string).lower()

            if not user_input or "no" in user_input or user_input[0] != "y":
                print("Skipping...")
                return

        try:
            if os.path.isfile(item_path):
                os.remove(item_path)

            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

        except Exception:
            print(f"Delete permission error: {item_path}", file=sys.stderr)

    def process_args(self):
        """
        Processes arguments and runs the search
        """

        desc = "Searches directories recessively and prints location of" \
               " Python's, Rust, and C# build locations, to be rebuilt " \
               "Skips `.git` directories. Does not follow symlinks."

        epilog = """Examples:
        List build environments in current directory:
        \trmenv

        Delete build environments and directories and files over 200M in directory 'code':
        \trmenv -s 200M -d code --delete"""

        parser = argparse.ArgumentParser(
            prog="rmvenv",
            description=desc,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter
        )

        parser.add_argument(
            "directory",
            help="Directory to search (by default current directory)",
            nargs="?"
        )

        size_help = "Mark files and directories over a given size in bytes. " \
                    "Doesn't have to be a build environment! " \
                    'Default size is 100M. Sizes can "1024", "50m", ' \
                    '"7.5G" ect.'

        parser.add_argument(
            "-s", "--size",
            action=SizeAction,
            nargs="?",
            help=size_help
        )

        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete marked items instead of printing them. Interactive"
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help="Don't ask for confirmation"
        )

        parser.add_argument(
            "--version",
            action="store_true",
            help="Print version and exit"
        )

        args = parser.parse_args()

        # Print version and exit
        if args.version:
            print(f"{parser.prog}: {VERSION}")
            sys.exit(0)

        if args.directory:
            path = args.directory
        else:
            path = "."

        if args.size:
            self.check_size = True
            self.mark_size_bytes = args.size

        self.delete_marked_items = args.delete
        self.force = args.force

        # Search the directory, printing the status while doing so

        self.status.start()

        # Evaluate the top level directory
        try:
            self.evaluate(path)
        
        except PermissionError:
            # Don't have permission to read file

            # Manage the status, as this is printed to stderr
            with self.status.text_lock:
                self.status.clear()

                # Print error information
                print(
                    f"Read permission error: {path}",
                    file=sys.stderr
                )

        self.search(path)
        self.status.stop()

    def process_marked_items(self):
        """
        Processes marked items. Prints or deletes them
        """

        marked_items_sorted = list(self.marked_items)
        marked_items_sorted.sort(key=lambda x: x.lower())

        if not self.delete_marked_items:
            for item_path in marked_items_sorted:
                print(item_path)

        else:
            for item_path in marked_items_sorted:
                self.delete_marked_item(item_path)


def debug():
    print("*" * 50, "DEBUG", "*" * 50)

    sizes = [10 ** i for i in range(13, 20)]
    for s in sizes:
        print(s, HumanFilesize(s))


def main():
    try:
        c = Cleaner()

        try:
            c.process_args()
            c.process_marked_items()

        except BaseException:
            # Tell the status thread to stop if it hasn't already
            c.status.stop_flag.set()

            # Re-raise the exception
            raise

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt", file=sys.stderr)

        if True:
            sys.exit(130)
        else:
            raise


if __name__ == "__main__":
    main()

# Build command:
# pyproject-build

# TODO: Figure out ModualNotFoundError lol

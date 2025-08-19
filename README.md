# rmvenv

Command line app to list and delete build environments. This only leaves
your source code and files to rebuild the environment, so they can be
easily backed up.

This software can identify Python
[virtual environments](https://docs.python.org/3/library/venv.html),
Rust's
[target](https://doc.rust-lang.org/cargo/commands/cargo-build.html)
directory, as well as java's `.class` files. If deleted, this
can save gigabytes of space, and they can be easily recreated and the
packages re-downloaded when the code needs to run again. This software can
also show and delete files and folders over a given size.

However, the exact version of the software may change if
dependences aren't managed well, and they may be removed from package
repositories. Hopefully these errors are rare.

## Installation

### Requirements

- Python >= 3.10
- pip

I think it's OS independent, but I've not tested it outside of a Linux
OS, so tread with caution.

### Steps

Open the command line and run

```
pip install rmvenv
```

On some Linux distributions [pipx](https://pipx.pypa.io/latest/)
may have to be used:

```
pipx install rmvenv
```

## Example uses

On the command line, to list virtual environments in the currently
directory, simply use:

```
rmvenv
```

To delete (interactively) build environments, as well as large files and
folders over 1 gigabytes in the folder `my_code`:

```
rmvenv -s 1G -d my_code --delete
```

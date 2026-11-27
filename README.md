# CanvasResults

CanvasResults is a Python Library to extend the ``canvasapi`` (https://github.com/ucfopen/canvasapi) Python package to support bulk uploading and downloading
of student Gradebook results.

The API provides generator functions to perform long tasks which yield progress so that you can build an application around the library.

This library was developed to support a handful of other programs I am building that require this functionality.

---

## Current Release

Version 0.0.1 supports bulk downloading of results from Canvas. Currently planned but unsupported are:
 - Support for student accounts to bulk download personal results. The code branch exists but is not properly tested and I believe a bug still remains
 - Bulk upload of results - skeleton but untested implementation. Testing to come at the end of next semester

---

## Installation

The latest version of the calculator can always be installed via:

```bash
pip install canvasapi
```

Installation automatically pulls in all required dependencies as listed below. You should consider installing within
a Python Virtual Environment.

| Required Package | Reason                                                                   |
|------------------|--------------------------------------------------------------------------|
| `pydantic`       | Validation of generated models and classes                               |
| `canvasapi`      | Interact with Canvas to download/upload results                          |

---

# Canvas Token

As with the ``canvasapi`` library, you will need to generate and provide your own Canvas API Token. This token is private and should **NOT** be made public

 1. Login to Canvas
 2. Click on **Account** at the top left of the page
 3. Select **Settings** from the menu that appears
 4. Click on **+ New access token**
 5. On the newly open page to create a token
    1. Enter a **Purpose** for the Access Token. This can be whatever you like
    2. Set **Expires** to the date you wish the Token to expire. Setting **Never** will mean you can continue to use the token for multiple years. Setting a 
       fixed date will require that you regenerate the token after it expires
 6. Click **Generate Token**
 7. The token will be displayed to screen. Copy and paste this into a local file immediately. Once you leave this web page, Canvas will not allow you to view 
    it again

The Token **MUST** always be kept private. This token will allow any application or user to access all of your Canvas Shells and update change anything. Do 
**NOT** provide this token to other people or students. Do not save this token in a shared directory

You may revoke your Token at any point via the **Account->Settings** page if it is compromised in any way or you no longer need it

---

# Testing the Installed Module

The ``canvasresults`` module can be tested directly from the command line after installation:

```
python -m canvasresults -h
usage: python -m canvasresults [-h] [-u URL] -t TOKEN -c COURSE -a ASSIGNMENT [ASSIGNMENT ...] [-v]

CanvasResults Module Testing

options:
  -h, --help            show this help message and exit
  -u, --url URL         Canvas URL (default: https://swinburne.instructure.com)
  -t, --token TOKEN     Canvas API token
  -c, --course COURSE   Canvas course name
  -a, --assignment ASSIGNMENT [ASSIGNMENT ...]
                        One or more Canvas assignment names
  -v, --verbose         Verbose mode. Causes python -m canvasresults to print debugging messages while running. Multiple -v options increase the verbosity.  The maximum is 2.
```

**NOTE:** The default Canvas URL will cause the test to try to apply your token to the Swinburne University Canvas site. Please replace URL for your organisation.

Assuming your generated Canvas API Token was `12345~ABCDEFGHIJKLMNOPQRSTUVWXYZ=` then:

```aiignore
python -m canvasresults -u https://organisation.instructure.com -t "12345~ABCDEFGHIJKLMNOPQRSTUVWXYZ=" -c ABC12345 -a "Lab 1" "Lab 2" "Test" -v
```

Will access the latest offering of Course ABC12345 at your Canvas Shell, download all student results for the assessments `Lab 1`, `Lab 2`, and `Test`, and then
display the downloaded Gradebook results to screen.

---

# `CanvasResults` API Documentation

Coming after finalisation of all features

For now, review the code in:

 - `__main__.py`
 - `canvasresults.py`

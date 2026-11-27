import logging
from enum import IntEnum, auto
from collections.abc import Iterator

import canvasapi
import canvasapi.course
import canvasapi.user
import canvasapi.assignment
from canvasapi.exceptions import CanvasException, BadRequest, InvalidAccessToken, Unauthorized, ResourceDoesNotExist, RequiredFieldMissing, Forbidden, RateLimitExceeded, Conflict, UnprocessableEntity

from pydantic import ConfigDict, validate_call

from typing import Annotated
from pydantic import StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
"""String with at least one character in it"""

from typing import Any

from typing import NotRequired, TypedDict, Mapping


class CanvasUploadEntry(TypedDict):
    result: int | float | str | None
    comment: NotRequired[str]


CanvasUploadData = Mapping[str, Mapping[str, CanvasUploadEntry]]


class CanvasResults:
    class CanvasError(Exception):
        """
        Re-raise all CanvasException types in a cleaner way with a better decoded error message
        """
        def __init__(self, exception: CanvasException):
            match exception:
                case InvalidAccessToken():
                    super().__init__(f'Unable to access Canvas: {exception.message[0]['message']}')
                case ResourceDoesNotExist():
                    super().__init__(f'Requested resource unavailable: {exception.message}')
                case _:
                    super().__init__(f'Unspecified Canvas error({exception.__class__.__name__}): {exception.message}')

    class NoMatchingCourses(LookupError):
        def __init__(self, search_key: str) -> None:
            super().__init__(f'No matching Courses found for search key: {search_key}')

    class MissingAssignmentError(ValueError):
        def __init__(self, assignment: str):
            super().__init__(f'Unable to locate required assignment in Canvas shell: {assignment}')
            self.assignment = assignment

    class _State(IntEnum):
        Initial = auto()
        CourseList = auto()
        CourseSet = auto()
        AssignmentList = auto()
        StudentsSelected = auto()

        def __str__(self):
            return self.name

    _NONE_RESETS = {_State.Initial: ('_course',),
                    _State.CourseList: ('_course',),
                    _State.CourseSet: (),
                    _State.AssignmentList: (),
                    _State.StudentsSelected: ()
                    }
    """Variables that should be set to None when in this state"""

    _DICT_RESETS = {_State.Initial: ('_courses', '_all_assignments', '_students', '_gradebook'),
                    _State.CourseList: ('_all_assignments', '_students', '_gradebook'),
                    _State.CourseSet: ('_all_assignments', '_students', '_gradebook'),
                    _State.AssignmentList: ('_students', '_gradebook'),
                    _State.StudentsSelected: ('_gradebook',)
                    }
    """Variables that should be set to an empty dictionary when in this state"""

    def __init__(self, canvas_url: str, token: str):
        self._log = logging.getLogger(f'{__package__}.{self.__class__.__name__}')

        self._log.info(f'Connecting to Canvas at {canvas_url} with provided token')
        try:
            self._canvas = canvasapi.Canvas(canvas_url, token)
            self._user: canvasapi.user.User = self._canvas.get_current_user()
            self._log.info(f'Connected to Canvas as {self._user.name}')
        except InvalidAccessToken as e:
            raise CanvasResults.CanvasError(e) from None

        # Create internal variables to store downloaded information from Canvas
        self._courses: list[canvasapi.course.Course] = []
        self._course: canvasapi.course.Course | None = None
        self._all_assignments: dict[str, canvasapi.assignment.Assignment] = {}
        self._students: dict[str, canvasapi.user.User] = {}
        self._gradebook: dict[str, dict[str, int | float | None]] = {}

        self._set_state(CanvasResults._State.Initial)

    def _set_state(self, state: CanvasResults._State) -> None:
        """
        Change the internal state of CanvasResults, resetting all internal variables based on State

        :param state: CanvasResults._State indicating new state
        """
        self._log.debug(f'Setting state to {state}')
        self._log.debug(f'  Resetting variables to None: {self._NONE_RESETS[state]}')
        self._log.debug(f'  Resetting variables to {{}}: {self._DICT_RESETS[state]}')
        for var in self._NONE_RESETS[state]: setattr(self, var, None)
        for var in self._DICT_RESETS[state]: setattr(self, var, {})
        self._state = state

    def find_courses(self, course_filter: str = '') -> Iterator[dict[str, int]]:
        """
        Find all Courses accessible via this Token whose names match the given filter

        The filtered Courses are stored as a list of ``canvasapi.course.Course`` and is accessible via ``CanvasResults.courses``

        :param course_filter: String containing a partial match to the Canvas Course name. Should be the Course Code
        :return: Iterator that yields the current progress of fetching and filtering the Course list accessible to the user
        :raise CanvasResults.NoMatchingCourses: If no Canvas Courses can be found that match the filter
        """
        self._log.info(f'Retrieving Canvas Courses that match: {course_filter}')

        matched: list[canvasapi.course.Course] = []
        for count, course in enumerate(self._canvas.get_courses(per_page=100), start=1):
            if course_filter in course.name:
                matched.append(course)
                # Only yield an update when a matched course is found
                yield {'matched_courses': len(matched), 'course_name': course.name}

        self._courses: list[canvasapi.course.Course] = sorted(matched, key=lambda u: u.created_at, reverse=True)

        if not self._courses: raise CanvasResults.NoMatchingCourses(course_filter)

        self._log.info(f'  Found: {', '.join([u.name for u in self._courses])}')
        self._set_state(CanvasResults._State.CourseList)

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    def set_course(self, course: canvasapi.course.Course) -> None:
        """
        Specify which Course in the previously retrieved courses list ``find_courses()`` all future operations will use

        The selected Course is stored as a ``canvasapi.course.Course`` and is accessible via ``CanvasResults.course``

        :param course: Canvas Course to select - **MUST** match one of the Courses returned by ``find_courses()``
        :raise RuntimeError: If method is called when internal state is not valid to call this method
        :raise ValueError: If selected Canvas Courses was not retrieved via earlier call to ``find_courses()``
        """
        if self._state < CanvasResults._State.CourseList: raise RuntimeError(f'{self.__class__.__name__}.set_course(): Attempting to set a Course without first calling {self.__class__.__name__}.find_courses()')

        if course not in self._courses: raise ValueError(f'{self.__class__.__name__}.set_course(): Course "{course.name}" not in list of filtered Courses')

        self._log.info(f'Setting Course to: {course.name}')
        self._course = course
        self._set_state(CanvasResults._State.CourseSet)

    def find_assignments(self) -> Iterator[dict[str, int | str]]:
        """
        Find all Assignments in the currently selected Course

        The Assignments are stored as a dictionary mapping the assignment name to a ``canvasapi.assignment.Assignment`` and is accessible via
        ``CanvasResults.assignments``

        :return: Iterator that yields the current progress of fetching and storing the assignments
        """
        if self._state < CanvasResults._State.CourseSet: raise RuntimeError(f'{self.__class__.__name__}.find_assignments(): Attempting to set a Course without first calling {self.__class__.__name__}.set_course()')

        # Will always succeed as _course MUST be set for self._state to pass the test above
        assert self._course is not None

        self._log.info(f'Retrieving Canvas Assignments for selected Course')
        for assignment in self._course.get_assignments():
            self._all_assignments[assignment.name] = assignment
            yield {'assignment_count': len(self._all_assignments), 'assignment_name': assignment.name}

        self._log.info(f'  Found: {', '.join([a.name for a in self._all_assignments.values()])}')
        self._set_state(CanvasResults._State.AssignmentList)

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    def validate_assignments(self, assignment_names: list[NonEmptyStr]) -> None:
        """
        Validate that the Course contains all the nominated assignments.

        We need to check the provided list of assignment names to the assignments stored in ``_all_assignments``

        :param assignment_names: List containing Canvas Assignment names that we need to validate
        :raise RuntimeError: If method is called when internal state is not valid to call this method
        :raise MissingAssignmentError: If not all required assignments were found in the Canvas Shell
        """
        if self._state < CanvasResults._State.AssignmentList: raise RuntimeError(f'{self.__class__.__name__}.validate_assignments(): Attempting to validate Assignments without first calling {self.__class__.__name__}.find_assignments()')

        # Will always succeed as _course MUST be set for self._state to pass the test above
        assert self._course is not None

        # Create set of all required assignments to look for and initialise internal lists of assignment information
        required_names = set(assignment_names)

        # Number width to nicely format debug messages
        debug_msg_format_width = len(str(len(required_names)))

        self._log.info(f'Checking that Course contains all required Assignments({required_names})')

        # For each requested assignment, check if it is in self._all_assignments
        for count, assignment in enumerate(assignment_names, start=1):
            if assignment in self._all_assignments:
                self._log.debug(f'  ✅ Found Assignment ({count:>{debug_msg_format_width}}/{len(required_names)}): {assignment}')
            else:
                self._log.debug(f'  ❌ Assignment not found ({count:>{debug_msg_format_width}}/{len(required_names)}): {assignment}')

        # Check we found all the required assignments and raise an exception if not
        missing_names: set[str] = required_names - set(self._all_assignments)
        if missing_names: raise CanvasResults.MissingAssignmentError(', '.join(sorted(missing_names)))

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    def select_students(self, student_filter: list[str] | None = None, section_filter: list[str] | None = None) -> None:
        """
        Select students from the Canvas Shell to download or upload results for. Students can be filtered to not extract the entire list of enrolled students

        Student information is stored as a dictionary mapping Canvas Student ID (SIS ID) to the ``canvasapi.user.User`` representing that student and is
        accessible via ``CanvasResults.students``

        :param student_filter: List of strings containing student IDs or ``None`` for all students - Filter students to only include selected students
        :param section_filter: List of strings containing section IDs or ``None`` for all Sections - Filter sections to only include selected Sections in Canvas.
                               **NOTE:** If both ``student_filter`` and ``section_filter`` are selected will filter to selected ``student_filter`` **only** if
                               those students are also in ``section_filter``
        :raise RuntimeError: If method is called when internal state is not valid to call this method
        """
        if self._state < CanvasResults._State.AssignmentList: raise RuntimeError(f'{self.__class__.__name__}.select_students(): Attempting to select students without first calling {self.__class__.__name__}.find_assignments()')

        # Will always succeed as _course MUST be set for self._state to pass the test above
        assert self._course is not None

        self._log.info(f'Downloading selected students records from {self._course.name}')

        if any(enrollment.type == "StudentEnrollment" for enrollment in self._course.get_enrollments(user_id=self._user.id)):
            self._log.info(f'  🧑‍🎓 Current user ({self._user}) is enrolled in {self._course.name} as a Student')

            self._students = {u.sis_user_id: u
                              for u in self._course.get_users(enrollment_type=["student"], enrollment_state=["active"])
                              if u.id == self._user.id
                              }
        else:
            self._log.info(f'  🧑‍🏫 Current user ({self._user}) is enrolled in course as a Teacher')

            selected_ids: set[str] | None = set(student_filter) if student_filter else None

            if student_filter: self._log.debug(f'  Filtering to student IDs: {selected_ids}')

            if section_filter:
                self._log.debug(f'  Filtering for students enrolled in section(s): {section_filter}')
                section_students = {enrollment.sis_user_id
                                    for section in self._course.get_sections()
                                    if any(sf in section.name for sf in section_filter)
                                    for enrollment in section.get_enrollments(type='StudentEnrollment')
                                    }

                selected_ids = (section_students if selected_ids is None else selected_ids & section_students)
                self._log.debug(f'  IDs matching all filters: {selected_ids}')

            self._students = {u.sis_user_id: u
                              for u in self._course.get_users(enrollment_type=["student"], enrollment_state=["active"])
                              if selected_ids is None or u.sis_user_id in selected_ids
                              }

            if len(self._students) == 0: raise LookupError(f'No students match provided filters: student_filter({', '.join(student_filter or [])}) section_filter({', '.join(section_filter or [])})')

        self._log.info(f'  ✅ Selected {len(self._students)} enrolled students')
        for student in self._students.values():
            self._log.debug(f'    🧑‍🎓 Student details: {student}')

        self._set_state(CanvasResults._State.StudentsSelected)

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    def download_gradebook(self, assignment_names: list[NonEmptyStr]) -> Iterator[dict[str, int | float | str | None]]:
        """
        Download all selected ``_download_assignments`` for all previously selected ``_students`` and store Canvas Gradebook results in the internal gradebook (``_gradebook``)

        The gradebook is stored as a dictionary mapping Canvas Student ID to a dictionary mapping the Canvas Assignment Name to the allocated score/grade
        The gradebook is accessing via ``CanvasResults.portfolio_gradebook``

        :raise RuntimeError: If method is called when internal state is not valid
        """
        if self._state < CanvasResults._State.StudentsSelected: raise RuntimeError(f'{self.__class__.__name__}.download_gradebook(): Attempting to download Gradebook without first calling {self.__class__.__name__}.select_students()')

        # Will always succeed as _course MUST be set for self._state to pass the test above
        assert self._course is not None

        if not assignment_names: raise RuntimeError(f'No downloadable assignment names were provided to {self.__class__.__name__}.download_gradebook()')

        missing_names: set[str] = set(assignment_names) - set(self._all_assignments)
        if missing_names: raise CanvasResults.MissingAssignmentError(', '.join(sorted(missing_names)))

        self._log.info(f'Downloading Assignment results from {self._course.name}')

        # Map Canvas Student ID to actual Student ID (SIS ID)
        student_id_map: dict[int, str] = {student.id: student_sis_id for student_sis_id, student in self._students.items()}
        # Map Canvas Assignment ID to the actual assignment details
        assign_by_id: dict[int, canvasapi.assignment.Assignment] = {assignment.id: assignment for assignment in self._all_assignments.values() if assignment.name in assignment_names}
        # Prepopulate gradebook for each student and assignment with a grade of None
        self._gradebook = {student: {assignment_name: None for assignment_name in assignment_names} for student in self._students.keys()}

        count: int = 0
        total_results = len(assignment_names) * len(self._students)

        # Manual testing seems to indicate that 158 students is the limit at which there are too many students, so to be safe if we have >100 we need to get all students and skip any we don't want
        for sub in self._course.get_multiple_submissions(student_ids=list(student_id_map) if len(student_id_map) <= 100 else 'all', assignment_ids=list(assign_by_id.keys())):
            # Retrieve the student ID for this submission using the mapping - None if student does not exist
            student_id = student_id_map.get(sub.user_id)
            # Student ID for submission not a valid student, likely "Test Student" in Canvas, ignore and move onto next
            if student_id is None: continue

            # Retrieve the assignment name for this submission and the allocated score
            assignment_name = assign_by_id[sub.assignment_id].name
            score = getattr(sub, 'score', None)

            # Store score as provided (or None if not submitted)
            self._gradebook[student_id][assignment_name] = score

            # Yield back one student result to manage progress update
            count += 1
            yield {'increment': 1, 'count': count, 'total': total_results, 'percentage': count / total_results, 'student_id': student_id, 'assignment_name': assignment_name, 'score': score}

        for student in self._students.keys(): self._log.debug(f'Student({self._students[student].sis_user_id}) Results({self._gradebook[self._students[student].sis_user_id]})')

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    def upload_gradebook(self, results: CanvasUploadData) -> Iterator[int]:
        """
        Upload results and optional comments to validated Canvas assignments.

        Input structure:
            SIS ID -> assignment name -> {
                "result": required result,
                "comment": optional comment
            }

        Yields 1 after each successful student-assignment upload.
        """
        if self._state < CanvasResults._State.StudentsSelected: raise RuntimeError(f'Attempting to upload results Gradebook without first calling {self.__class__.__name__}.select_students()')

        if not self._upload_assignments: raise RuntimeError(f'No uploadable assignment names were provided to {self.__class__.__name__}.validate_assignments()')

        for sis_id, student_results in results.items():
            student = self._students.get(sis_id)

            if student is None:
                raise KeyError(f'Student SIS ID "{sis_id}" is not among the selected students')

            for assignment_name, upload in student_results.items():
                assignment = self._upload_assignments.get(assignment_name)

                if assignment is None:
                    raise CanvasResults.MissingAssignmentError(assignment_name)

                # Required by the requested payload contract.
                if "result" not in upload:
                    raise ValueError(f'Missing required "result" for student {sis_id}, 'f'assignment "{assignment_name}"')

                result = upload['result']
                comment = upload.get('comment')

                submission = assignment.get_submission(student.id)

                edit_arguments: dict[str, Any] = {'submission': {'posted_grade': result}}

                # Empty comments are not uploaded.
                if comment:
                    edit_arguments['comment'] = {'text_comment': comment}

                try:
                    submission.edit(**edit_arguments)
                except CanvasException as exception:
                    self._log.error(f'Failed to upload result for student {sis_id} to {assignment_name}')
                    raise CanvasResults.CanvasError(exception) from None

                self._log.debug(f'Uploaded student({sis_id}), assignment({assignment_name}), result({result}), comment({bool(comment)})')

                yield 1

    @property
    def user(self) -> canvasapi.user.User:
        """Return the user attached with this API Token"""
        return self._user

    @property
    def courses(self) -> list[canvasapi.course.Course]:
        """:return: List of Courses matching provided Course filter"""
        if not self._courses: raise RuntimeError(f'Attempting to retrieve {self.__class__.__name__}.courses without first calling {self.__class__.__name__}.find_courses()')
        return self._courses

    @property
    def course(self) -> canvasapi.course.Course:
        """:return: Selected Canvas Course"""
        if self._course is None: raise RuntimeError(f'Attempting to retrieve {self.__class__.__name__}.course without first calling {self.__class__.__name__}.set_course()')
        return self._course

    @property
    def assignments(self) -> dict[str, canvasapi.assignment.Assignment]:
        """:return: Dictionary mapping Assignment name to Assignment instances for all assignments in the selected Course"""
        if not self._all_assignments: raise RuntimeError(f'Attempting to retrieve {self.__class__.__name__}.assignments without first calling {self.__class__.__name__}.find_assignments()')
        return self._all_assignments

    @property
    def students(self) -> dict[str, canvasapi.user.User]:
        """:return: Selected students as a dictionary mapping Student ID to Canvas User"""
        if len(self._students) == 0: raise RuntimeError(f'Attempting to retrieve CanvasResults.students without first calling {self.__class__.__name__}.select_students()')
        return self._students

    @property
    def result_count(self) -> int:
        """:return: Calculated number of results in the downloaded gradebook"""
        if not self._gradebook: raise RuntimeError(f'No results downloaded to return information for')
        return sum(len(results) for results in self._gradebook.values())

    @property
    def gradebook(self) -> dict[str, dict[str, int | float | None]]:
        """:return: Dictionary mapping Student ID to a dictionary mapping the Canvas Assignment Name to the allocated score/grade for that student"""
        if len(self._gradebook) == 0: raise RuntimeError(f'Attempting to retrieve CanvasResults.gradebook without first calling {self.__class__.__name__}.download_gradebook()')
        return self._gradebook

    @property
    def gradebook_str(self) -> str:
        """:return: String representation of the Downloaded Gradebook for display purposes"""
        if not self._gradebook: raise RuntimeError(f'No results downloaded to return information for')
        return f'Downloaded {self.result_count} ({len(self._gradebook)} students x {len(next(iter(self._gradebook.values())))} assignments) Gradebook results'

# Sample code to delete an existing canvas comment
# def update_automated_result(canvas, course, assignment, user_id, new_grade, new_comment):
#     # 1. Fetch submission and explicitly include existing comments
#     submission = assignment.get_submission(user_id, include=["submission_comments"])
#
#     # 2. Check if a comment already exists
#     comments = getattr(submission, 'submission_comments', [])
#     if comments:
#         # Assuming you only expect one comment, target the first one
#         existing_comment_id = comments[0]['id']
#
#         # 3. Construct the exact Canvas REST API endpoint path for that specific comment
#         comment_endpoint = (
#             f"courses/{course.id}/assignments/{assignment.id}/"
#             f"submissions/{user_id}/comments/{existing_comment_id}"
#         )
#
#         # 4. Fire a raw DELETE request via the canvasapi internal requester
#         # This completely strips out the old automated message from the timeline
#         canvas._requester.request("DELETE", comment_endpoint, clean_url=True)
#
#     # 5. Push the new grade and the fresh automated text comment cleanly
#     submission.edit(
#         submission={"posted_grade": new_grade},
#         comment={"text_comment": new_comment}
#     )

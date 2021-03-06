#!/Library/Frameworks/Python.framework/Versions/2.7/bin/python

import re
import copy
import json
import qs


class QSAPIWrapper(qs.APIWrapper):
    """An API Wrapper specific for the QuickSchools API.

    Attributes:
        live: Whether or not this is accessing the live QS server (or backup).
        schoolcode: The schoolcode that this wrapper is accessing.
        api_key: The API key being used for requests.

    Args:
        access_key: An API key or schoolcode to access the school by. If a
            schoolcode is supplied, its API key will be retrivied via
            qs.api_keys.
            If an API key is supplied, it will both be used here
            and then stored in the API key store for future use *if the request
            is successful*.
            The access_key defaults to `qstools` for convenience while testing,
            but since it's the first argument, `qs.API('someschool')` works to
            set a different school.
        server: which server to use. Options:
            live
            backup
            local

    Methods that involve an API call have a set of kwargs that can be applied:
        critical: If True, then logger.critical will be called upon failure.
        fields: A list or string of fields to add to the 'fields' param.
        use_cache: (request-specific) If False, the cache will be ignored and
            reset for that resource.
        by_id: (request with list result specific) If True, return the data in
            a dict with {id: dict} values.
    """

    def __init__(self, access_key='qstools', server='live'):
        self._access_key = access_key
        self.server = server

        self._teacher_cache = qs.ListWithIDCache(sort_key='fullName')
        self._semester_cache = qs.ListWithIDCache()
        self._student_cache = qs.ListWithIDCache(sort_key='fullName')
        self._parent_cache = qs.ListWithIDCache(sort_key='fullName')
        self._section_cache = qs.ListWithIDCache(sort_key='sectionName')
        self._section_enrollment_cache = qs.ListWithIDCache()
        self._assignment_cache = qs.ListWithIDCache(sort_key='name')
        self._grade_cache = qs.ListWithIDCache(id_key='_qstools_id')
        self._report_cycle_cache = qs.ListWithIDCache()
        self._report_card_cache = qs.ListWithIDCache(id_key='_qstools_id')
        self._transcript_cache = qs.ListWithIDCache(id_key='studentId')
        self._class_cache = qs.ListWithIDCache(sort_key='sortOrder')

        self.schoolcode = None
        self.api_key = None

        self._parse_access_key()

    # =====================
    # = Semesters & Years =
    # =====================

    def get_semesters(self, **kwargs):
        """GET all semesters from /semesters."""
        cache = self._semester_cache
        if _should_make_request(cache, **kwargs):
            request = self._request('GET all semesters',
                '/semesters',
                **kwargs)
            semesters = self._make_request(request, **kwargs)
            cache.add(semesters)
        return cache.get(**kwargs)

    @qs.clean_arg
    def get_semester(self, semester_id, **kwargs):
        """GET a specific semester by id."""
        return self._make_single_request(
            semester_id,
            '/semesters',
            self.get_semesters,
            'GET semester by ID',
            **kwargs)

    def get_active_semester(self):
        """GET the active semester dict."""
        return [i for i in self.get_semesters() if i['isActive']][0]

    def get_active_semester_id(self):
        """GET the id of the active semester."""
        return qs.clean_id(self.get_active_semester()['id'])

    def get_active_year_id(self):
        """GET the active year id."""
        return qs.clean_id(self.get_active_semester()['yearId'])

    def get_semesters_from_year(self, year_id=None):
        """GET a list of all semesters from a specific year. If year_id isn't
        specified, defaults to the current year.
        """
        year_id = year_id or self.get_active_year_id()
        return [i for i in self.get_semesters() if i['yearId'] == year_id]

    # ============
    # = Classes =
    # ============

    def get_classes(self, **kwargs):
        """GET classes via the /classes endpoint.

        Only gets classes from the current semester, as per the API docs.
        """
        cache = self._class_cache
        if _should_make_request(cache, **kwargs):
            request = self._request('GET classes', '/classes', **kwargs)
            cache.add(self._make_request(request, **kwargs))
        return cache.get(**kwargs)

    @qs.clean_arg
    def get_class(self, class_id, **kwargs):
        """GET a specific class by id."""
        return self._make_single_request(
            class_id,
            '/classes',
            self.get_classes,
            'GET class by ID',
            **kwargs)

    @qs.clean_arg
    def match_class(self, source_class_id, **kwargs):
        """Get a match for a class from a previous semester.

        The match is by name and the matching class has to be in the current
        semester.

        Returns a class dictionary or None

        Args:
            source_class_id: the id of the class to match from.
        """
        source_class = self.get_class(source_class_id)
        for current_class in self.get_classes():
            if current_class['name'] == source_class['name']:
                return current_class

    # ============
    # = Teachers =
    # ============

    def get_teachers(self, **kwargs):
        """GET teachers via the /teachers endpoint."""
        cache = self._teacher_cache
        if _should_make_request(cache, **kwargs):
            request = self._request('GET teachers', '/teachers', **kwargs)
            cache.add(self._make_request(request, **kwargs))
        return cache.get(**kwargs)

    def get_teacher(self, teacher_id, **kwargs):
        """GET a specific teacher by id."""
        return self._make_single_request(
            teacher_id,
            '/teachers',
            self.get_teachers,
            'GET teacher by ID',
            **kwargs)

    # ============
    # = Students =
    # ============

    def get_students(self, search=None, show_deleted=False,
            show_has_left=False, ignore_deleted_duplicates=False, **kwargs):
        """GET a list of all enrolled students from /students.

        Args:
            search: add a search string as per API docs
            show_deleted: Show deleted students.
            show_has_left: Show students that have left.
            ignore_deleted_duplicates: Ignore any students that are deleted
                and have a fullName that matches another student, deleted or
                not. This is useful if the student names need to be unique, but
                there are deleted copies of real students. This is mute
                unless show_deleted=True.
        """
        cache = self._student_cache

        if show_deleted or show_has_left:
            request = self._request(
                'GET all students, including deleted/has left',
                '/students',
                **kwargs)
            request.params = {
                'showDeleted': show_deleted,
                'showHasLeft': show_has_left,
                'search': search
            }
            request.fields += ['hasLeft', 'deleted']
            students = self._make_request(request, **kwargs)

            if ignore_deleted_duplicates:
                duplicates = qs.find_dups_in_dict_list(students, 'fullName')
                students = qs.dict_list_to_dict(students)
                for dup in duplicates:
                    if dup['hasLeft'] is True or dup['deleted'] is True:
                        del students[dup['id']]
                students = qs.dict_to_dict_list(students)

            if kwargs.get('by_id') is True:
                students = qs.dict_list_to_dict(students)
            return students
        elif _should_make_request(cache, **kwargs):
            request = self._request('GET all students', '/students', **kwargs)
            request.params = {'search': search}
            students = self._make_request(request, **kwargs)
            cache.add(students)
        return cache.get(**kwargs)

    @qs.clean_arg
    def get_student(self, student_id, **kwargs):
        """GET a specific student by id.

        #TODO bug: if a student is looked up that wasn't already in the cache,
        it doesn't get cached
        """
        return self._make_single_request(
            student_id,
            '/students',
            self.get_students,
            'GET student by id',
            **kwargs)

    def get_students_by_name(self, student_name, **kwargs):
        """GET students by name. Returns a list of all possible matches."""
        return [
            i for i in self.get_students(**kwargs)
            if student_name in i['fullName']
        ]

    # ===========
    # = Parents =
    # ===========

    def get_parents(self, **kwargs):
        """GET a list of all parents from /parents."""
        cache = self._parent_cache
        if _should_make_request(cache, **kwargs):
            request = self._request('GET all parents', '/parents', **kwargs)
            parents = self._make_request(request, **kwargs)
            cache.add(parents)
        return cache.get(**kwargs)

    @qs.clean_arg
    def get_parent(self, parent_id, **kwargs):
        """GET a specific parent by id."""
        return self._make_single_request(
            parent_id,
            '/parents',
            self.get_parents,
            'GET parent by id',
            **kwargs)

    # ============
    # = Sections =
    # ============

    def get_sections(self, semester_id=None, all_semesters=False,
            active_only=True, **kwargs):
        """GET sections from the /sections endpoint.

        Args:
            semester_id: GET sections from a specific semester by id.
            all_semesters: GET sections from all semesters for this school.
                semester_id get priority over this.
            active_only: Only return sections from the current semester. If
                this is False, sections from all semesters already in the cache
                are returned, otherwise it's the active semester only.
                all_semesters and semester_id get priority.
        """
        cache = self._section_cache

        def mark_sections(sections, semester_id_to_mark):
            for section in sections:
                section.update({'semesterId': semester_id_to_mark})

        if semester_id:
            semester_id = qs.clean_id(semester_id)
            kwargs.update({'cache_filter': {'semesterId': semester_id}})

            if _should_make_request(cache, **kwargs):
                request = self._request(
                    'GET sections from semester',
                    '/sections',
                    **kwargs)
                request.params.update({'semesterId': semester_id})
                sections = self._make_request(request, **kwargs)
                if not sections:
                    return []
                mark_sections(sections, semester_id)
                cache.add(sections)

        elif _should_make_request(cache, **kwargs):
            request = self._request('GET sections', '/sections', **kwargs)
            sections = self._make_request(request, **kwargs)
            mark_sections(sections, self.get_active_semester_id())
            cache.add(sections)

        if all_semesters is True:
            active_only = False
            all_sections = []
            for semester in self.get_semesters():
                sections = self.get_sections(semester_id=semester['id'])
                all_sections.append(sections)

        if semester_id is None and active_only is True:
            semester_id_dict = {'semesterId': self.get_active_semester_id()}
            kwargs.update({'cache_filter': semester_id_dict})

        if not cache.has_fields('semesterId'):
            qs.logger.warning("Not all cached sections have semester ids", {})

        return cache.get(**kwargs)

    @qs.clean_arg
    def get_section(self, section_id, **kwargs):
        """GET a section by id."""
        cache = self._section_cache

        should_make_req_kwargs = qs.merge(kwargs, {'identifier': section_id})
        if _should_make_request(cache, **should_make_req_kwargs):
            request = self._request(
                'GET section by id',
                '/sections/{}'.format(section_id),
                **kwargs)
            request.fields += ['smsAcademicSemesterId']
            section = self._make_request(request, **kwargs)
            self.get_sections(semester_id=section['smsAcademicSemesterId'],
                **kwargs)
        return cache.get(section_id, **kwargs)

    def match_section(self, identifier, target_semester_id=None,
            student_id=None, allow_multiple=False, fail_silent=False,
            critical=False, match_name=True, match_code=True,
            match_class_id=False, match_class_name=True, match_teachers=True, **kwargs):
        """Match a section based on id, name, or section dict.

        Args:
            identifier: The identifier to match on. There are a few options for
                for what to pass here with different behaviors:
                    section name: match based on the section name only
                    identifier: lookup the section by id
                    a dict: match the values in this dict
            target_semester_id: Look for matches in this semester. Defaults to
                the current semester
            student_id: If supplied, limits possible matched sections to those
                taken by this student.
            allow_multiple: Allow multiple matches. A list is always returned
                if there are matches, else None (or raise an error).
            fail_silent: If supplied, sections without matches will be returned
                with a value of "FALSE"
            critical: Make a critical log if there isn't the correct number of
                matches. If this is False, None is returned with the incorrect
                number.
            match_*: determine whether this value needs to match in the
                returned section.
        Returns:
            If there are 0 matches, returns None (or make a critical log if
                critical is True)
            Else if allow_multiple is True, returns a list
            Else if there is 1 match, returns that match
            Else return None or make a critical log.
        """
        # validate and normalize input
        section_dict = {}
        if qs.is_valid_id(identifier, check_only=True):
            identifier = qs.clean_id(identifier)
            if identifier.isdigit():
                section_dict = self.get_section(identifier)
                section_dict['teacherIds'] = {
                    i['id'] for i in section_dict['teachers']
                }
            else:
                section_dict = {'sectionName': qs.clean_id(identifier)}
        elif type(identifier) is dict:
            section_dict = identifier
        else:
            raise TypeError(
                'identifier must be a section id, section name, or section '
                'dict.')

        # get candidate pool
        target_semester_id = (
            qs.clean_id(target_semester_id)
            if target_semester_id
            else self.get_active_semester_id())
        semester_id_kwarg = {'semester_id': target_semester_id}
        if student_id:
            student_id = qs.clean_id(student_id)
            all_enrolled = self.get_student_enrollment(
                student_id,
                semester_id=target_semester_id)
            candidate_pool = [self.get_section(i) for i in all_enrolled]
        else:
            candidate_pool = self.get_sections(semester_id=target_semester_id)

        def dealbreaker(should_match, key):
            if should_match is False:
                return False
            elif key not in section_dict:
                return False
            else:
                return section_dict.get(key) != candidate.get(key)

        # actually search for matches
        matches = []
        for candidate in candidate_pool:
            teacher_ids = set([i['id'] for i in candidate['teachers']])
            candidate['teacherIds'] = teacher_ids
            if dealbreaker(match_name, 'sectionName'): continue
            if dealbreaker(match_code, 'sectionCode'): continue
            if dealbreaker(match_class_id, 'classId'): continue
            if dealbreaker(match_class_name, 'className'): continue
            if dealbreaker(match_teachers, 'teacherIds'): continue
            matches.append(candidate)
        qs.sets_to_lists(matches)
        qs.sets_to_lists([section_dict])

        # try to return a match
        try:
            if len(matches) == 0:
                if not fail_silent:
                    raise LookupError('No matches found for section. Identifier: {}'.format(identifier))
                else:
                    return "FALSE"
            elif allow_multiple:
                return matches
            elif len(matches) == 1:
                return matches[0]
            else:
                raise LookupError(
                    'Too many ({}) matches found for section'
                    ''.format(len(matches)))
        except LookupError as e:
            logger_args = (e.args[0], {
                'candidate pool size': len(candidate_pool),
                'section': section_dict,
                'matches': matches,
                'student ID': student_id,
                'semester ID': target_semester_id,
            })
            if critical is True:
                qs.logger.critical(*logger_args)
            else:
                qs.logger.error(*logger_args)
                return None

    def post_section(self, section_name, section_code, class_id, teacher_id,
            credit_hours=1, **kwargs):
        """POST to create a new section. teacher_id should be a single
        teacher id or a list of teacher ids.
        """
        teacher_ids = teacher_ids if type(teacher_id) is list else [teacher_id]

        request = self._request('POST new section', '/sections', **kwargs)
        request.verb = qs.POST
        request.params = {'fields': 'smsAcademicSemesterId'}
        request.request_data = {
            'classId': class_id,
            'sectionName': section_name,
            'sectionCode': section_code,
            'creditHours': credit_hours,
            'teacherIds': json.dumps(teacher_ids)
        }
        response = self._make_request(request, **kwargs)
        if request.successful is True:
            response['semesterId'] = response['smsAcademicSemesterId']
            self._section_cache.add(response)
        return response

    def post_sections(self, sections_dict, print_log=False, **kwargs):
        """POST to create a new sections from a dict of section
        information. Teacher_id should be a single teacher id or a list
        of teacher ids. The print_log param is to log and print section_code
        info as the sections are created:

        Dict structure should be as such:
        {'section_code':  {'section_name': section_name,
                           'section_code': section_code,
                           'class_id:': class_id,
                           'teacher_id': teacher_id,
                           'credit_hours': credit_hours}}
        Note: credit_hours is optional
        """
        for section in qs.bar(sections_dict):
            new_sect = sections_dict[section]

            if 'credit_hours' in new_sect:
                new_section = self.post_section(section_name=new_sect['section_name'],
                                                section_code=new_sect['section_code'],
                                                class_id=new_sect['class_id'],
                                                teacher_id=new_sect['teacher_id'],
                                                credit_hours=new_sect['credit_hours'])
            else:
                new_section = self.post_section(section_name=new_sect['section_name'],
                                                section_code=new_sect['section_code'],
                                                class_id=new_sect['class_id'],
                                                teacher_id=new_sect['teacher_id'])

            if print_log:
                qs.logger.info({"section name": new_section['sectionName'],
                                "class name": new_section['className'],
                                "id": new_section['id']}, cc_print=True)

        return None

    @qs.clean_arg
    def update_section(self, section_id, section_dict, **kwargs):
        """POST to update an existing section by id. section_id should be a
        dict of values to update, as per the API reference.
        """
        request = self._request(
            'POST to update existing section',
            '/sections/{}'.format(section_id),
            **kwargs)
        request.verb = qs.POST
        request.request_data = section_dict
        return self._make_request(request, **kwargs)

    @qs.clean_arg
    def delete_section(self, section_id, delete_enrollment=False, **kwargs):
        """DELETE an existing section by id.

        If delete_enrollment is True, this will delete enrollment first, then
        delete the section.
        """
        if delete_enrollment:
            self.delete_all_section_enrollments_for_section(section_id)

        request = self._request(
            'DELETE section by id',
            '/sections/{}'.format(section_id),
            **kwargs)
        request.verb = qs.DELETE
        response = self._make_request(request, **kwargs)
        if request.successful:
            self._section_cache.invalidate(section_id)
        return response

    # =======================
    # = Section Enrollments =
    # =======================

    def get_section_enrollments(self, **kwargs):
        """GET section enrollments for the active semester.
        For speed, uses an extra field in the /students endpoint. Data is still
        stored in the cache by section id.

        Takes the sames kwargs as `.get_sections()` for deciding which
        sections to show.

        #TODO: by default return the 'students' list, not the full API obj
        """
        self._update_section_enrollment_cache()
        by_id = kwargs.get('by_id')

        section_enrollment_kwargs = qs.merge(kwargs, {'by_id': False})
        section_kwargs = qs.merge(kwargs, {'by_id': True})
        all_enrollment = [
            self.get_section_enrollment(i)
            for i in self.get_sections(**section_kwargs)
        ]
        if by_id:
            return qs.dict_list_to_dict(all_enrollment)
        else:
            return all_enrollment

    @qs.clean_arg
    def get_section_enrollment(self, section_id, **kwargs):
        """GET section enrollment for a specific section ID. Note that if the
        section is from a non-active semester, this is the only way to access
        that section's enrollment.
        """
        cache = self._section_enrollment_cache

        self._update_section_enrollment_cache()
        cached = cache.get(section_id, **kwargs)

        if cached:
            return cached
        else:
            request = self._request(
                'GET section enrollment for non-active section',
                '/sectionenrollments/{}'.format(section_id),
                **kwargs)
            students = self._make_request(request, **kwargs)['students']
            section_enrollments = {'id': section_id, 'students': []}
            section_enrollments['students'] = [
                self._enrollment_dict(i) for i in students
            ]
            cache.add(section_enrollments)
        return cache.get(section_id, **kwargs)

    def get_student_enrollments(self, **kwargs):
        """GET the section enrollment by student, for all students/sections.
        Accepts the same kwargs as `.get_sections()` for determining which
        sections to show.

        Returns: A dict, by student id, of all sections that student takes:
        {
            "300794": [
                "694520",
                "694521"
            ],
            ...
        }

        If by_id in the kwargs is True, a list is returned:
        [
            {
                "id": "300794"
                "sections": [
                    "694520",
                    "694521"
                ]
            },
            ...
        ]
        """
        by_id = kwargs.get('by_id')

        by_section = self.get_section_enrollments(**kwargs)
        if type(by_section) is list:
            by_section = qs.dict_list_to_dict(by_section)

        all_students = {}
        for section_id, student_list in by_section.iteritems():
            for student_id in [i['id'] for i in student_list['students']]:
                if student_id not in all_students:
                    all_students[student_id] = []
                all_students[student_id].append(section_id)

        if by_id is True:
            return all_students
        else:
            student_list = []
            for student_id, sections in all_students.iteritems():
                student_list.append({
                    'id': student_id,
                    'sections': sections,
                })
            return student_list

    @qs.clean_arg
    def get_student_enrollment(self, student_id, **kwargs):
        """GET the sections a specific student is enrolled in, by ID.
        Accepts the same kwargs as `.get_sections()` for determining which
        sections to show.
        """
        enrollments = self.get_student_enrollments(by_id=True, **kwargs)
        return enrollments.get(student_id)

    @qs.clean_arg
    def post_section_enrollment(self, section_id, student_ids, **kwargs):
        """POST enrollment to enroll all students in student ids to
        section_id. section_ids should be a list of student ids."""
        request = self._request(
            'POST section enrollment',
            '/sectionenrollments/{}'.format(section_id),
            **kwargs)
        request.request_data = {'studentIds': json.dumps(student_ids)}
        request.verb = qs.POST
        return self._make_request(request, **kwargs)

    @qs.clean_arg
    def delete_section_enrollments(self, section_id, student_ids,
            **kwargs):
        """DELTE all enrollments for a given section.

        student_ids should be a list of student ids, and, if supplied,
        only those students are unenrolled.
        """
        if type(student_ids) is not list:
            raise TypeError("student_ids should be list")
        elif len(student_ids) == 0:
            raise ValueError("student_ids can't be empty list")

        request = self._request(
            'DELETE section enrollments',
            '/sectionenrollments/{}'.format(section_id),
            **kwargs)
        request.verb = qs.DELETE
        request.request_data = {
            'studentIds': json.dumps(student_ids)
        }
        response = self._make_request(request, **kwargs)
        if request.successful:
            self._section_enrollment_cache.invalidate(section_id)
        return response

    @qs.clean_arg
    def delete_section_enrollment(self, section_id, student_id, **kwargs):
        """DELETE enrollment for a single student in a single section"""
        student_id = qs.clean_id(student_id)
        return self.delete_section_enrollments(section_id, [student_id])

    @qs.clean_arg
    def delete_all_section_enrollments_for_section(self, section_id, **kwargs):
        """"Delete all the sections enrollments for a section"""
        to_delete = self.get_section_enrollment(section_id)
        to_delete = [i['smsStudentStubId'] for i in to_delete['students']]
        if to_delete:
            self.delete_section_enrollments(section_id, to_delete)

    @qs.clean_arg
    def check_section_enrollment_match(self, section_1_id, section_2_id):
        """Checks that enrollment in section_1 and section_2 match exactly"""
        section_2_id = qs.clean_id(section_2_id)

        def enrollment_ids(section_id):
            enrollment = self.get_section_enrollment(section_id)['students']
            return set([i['id'] for i in enrollment])

        return enrollment_ids(section_1_id) == enrollment_ids(section_2_id)

    # ===============
    # = Assignments =
    # ===============

    def get_assignments(self, section_id, include_final_grades=False,
            include_grades=False, **kwargs):
        """GET a list of assignments for the specified section_id.

        Args:
            include_final_grades: Boolean whether to include final grade
                assignments or not.
            include_grades: Boolean whether to include the grades as well. If
                True, will return something like this:
                `[
                    {
                        "categoryId": "44767",
                        "categoryName": "Assignment",
                        ...
                        "grades": [
                            {
                                "studentId": "11345",
                                "marks": "100",
                                ...
                            },
                            ...
                        ]
                    },
                    ...
                ]`

        Note that the assignments cache will always have all the assignments
        for a section_id if it has any, but is organized by assignmentId. If
        an assignment is retrieved via get_assignment, it won't have a
        sectionId and thus will be re-retrieved in get_assignments for that
        section.
        """
        cache = self._assignment_cache
        by_id = kwargs.get('by_id')
        kwargs['cache_filter'] = {'sectionId': section_id}
        if include_final_grades is True:
            kwargs['cache_filter'].update({
                'isFinalGrade': True
            })

        if _should_make_request(cache, **kwargs):
            request = self._request(
                'GET assignments for section',
                '/sections/{}/assignments'.format(section_id),
                **kwargs)
            request.params.update({
                'includeFinalGrades': include_final_grades
            })
            request.fields.append('sectionId')
            assignments = self._make_request(request, **kwargs)
            cache.add(assignments)

        if include_grades is True:
            kwargs['cache_filter'] = {'sectionId': section_id}
            return self._assignments_with_grades(**kwargs)
        else:
            return cache.get(**kwargs)

    @qs.clean_arg
    def get_assignment(self, assignment_id, include_grades=False, **kwargs):
        """GET a specific assignment by ID."""
        cache = self._assignment_cache
        kwargs.update({'identifier': assignment_id})
        if _should_make_request(cache, **kwargs):
            request = self._request(
                'GET assignment',
                '/assignments/{}'.format(assignment_id),
                **kwargs)
            request.fields.append('sectionId')
            assignment = self._make_request(request, **kwargs)
            cache.add(assignment)

        if include_grades is True:
            # kwargs['cache_filter'] = {'assignmentId': assignment_id}
            # return self._assignments_with_grades(**kwargs)

            # Assembla #2219, #2218
            raise TypeError('include_grades cannot be true for get_assignment')
            # TODO: after #2219, sectionId doesn't have to be known
        else:
            return cache.get(**kwargs)


    @qs.clean_arg
    def get_grade_category_ids(self, section_id, **kwargs):
        """ GET grade category ids from assignments. Requires a section setup with
            assignments in all categories. Returns a dict in the form:
                {"category_name": "category_id"}
            where all category_ids are unique.
        """

        section_assignments = self.get_assignments(section_id)
        category_ids = {}
        duplicate_category_names = []
        for assignment in section_assignments:
            category_name = assignment['categoryName']
            category_id = assignment['categoryId']
            if category_name not in category_ids:
                category_ids[category_name] = category_id
            else:
                duplicate_category_names.add(category_name)

        if duplicate_category_names:
            qs.logger.info('Duplicate categories: {}' . duplicate_category_names, cc_print=True)

        return category_ids

    @qs.clean_arg
    def post_assignment(self, section_id, name, date, total_marks_possible,
            column_category_id=None, grading_scale_id=None, **kwargs):
        """POST an assignment to section with id=section_id."""
        uri = '/sections/{}/assignments'.format(section_id)
        request = self._request('POST an assignment', uri, **kwargs)
        request.verb = qs.POST
        request.request_data = {
            'name': name,
            'date': date,
            'totalMarksPossible': total_marks_possible,
            'columnCategoryId': column_category_id,
            'gradingScaleId': grading_scale_id,
        }
        response = self._make_request(request, **kwargs)
        if request.successful is True:
            self._assignment_cache.add(response)
        return response

    @qs.clean_arg
    def delete_assignment(self, section_id, assignment_id, **kwargs):
        """DELETE the assignment provided"""
        request = self._request(
            'DELETE assignment by id',
            '/sections/{}/assignments/{}'.format(section_id, assignment_id),
            **kwargs)
        request.verb = qs.DELETE
        response = self._make_request(request, **kwargs)
        if request.successful:
            self._assignment_cache.invalidate(assignment_id)
        return response

    # ==========
    # = Grades =
    # ==========

    @qs.clean_arg
    def get_grades(self, section_id, assignment_id=None, student_id=None,
            **kwargs):
        """GET all grades for a section.

        Args:
            section_id: The section_id to GET grades for. This is mandatory.
            assignment_id: The assignment to GET grades.
            student_id: Filter the grades for an existing section or assignment
                down to a specific student id.

        #TODO: Assembla #2219 is now deployed, so section_id can be None
        #TODO: include some way to not get final grades

        Note that since grades do not have API
        assigned id's but the cache relies on an id, a unique id is generated
        by this method. As a result, by_id=True will give a dictionary with
        meangingless keys (though meaningful values).
        """
        cache = self._grade_cache
        section_id = qs.clean_id(section_id) if section_id else None
        assignment_id = qs.clean_id(assignment_id) if assignment_id else None
        student_id = qs.clean_id(student_id) if student_id else None

        kwargs['cache_filter'] = {'sectionId': section_id}
        if _should_make_request(cache, **kwargs):
            request = self._request('GET all grades for a section',
                '/grades',
                **kwargs)
            request.params['sectionId'] = section_id
            grades = self._make_request(request, **kwargs)
            for grade in grades:
                grade['sectionId'] = section_id
                grade['_qstools_id'] = qs.make_id(
                    grade['studentId'],
                    grade['assignmentId'],
                    grade['sectionId'])
            cache.add(grades)

        if assignment_id:
            kwargs['cache_filter'].update({'assignmentId': assignment_id})
        if student_id:
            kwargs['cache_filter'].update({'studentId': student_id})
        return cache.get(**kwargs)

    def post_grades(self, section_id, assignment_id, grades, **kwargs):
        """POST grades to /grades endpoint.

        grades arg should be dict like at
        http://apidocs.quickschools.com/#assignment:

        [
            {
                studentId: ...
                marks: ...
            }
        ]
        """
        assignment_id = qs.clean_id(assignment_id)

        request = self._request('POST grades for assignment',
            '/grades',
            **kwargs)
        request.verb = qs.POST
        request.request_data = {
            'sectionId': section_id,
            'assignmentId': assignment_id,
            'grades': json.dumps(grades)
        }
        response = self._make_request(request, **kwargs)
        if request.successful is True:
            self._grade_cache.invalidate()
        return response

    def post_assignment_with_grades(self, section_id, assignment_name,
            assignment_date, total_marks_possible, category_id, grading_scale_id,
            student_ids_and_grades_list):
        """ POST new assignment and then POST grades to this same assignment.
            Please note that this method is dependant on post_assignment
            and post_grades. As a result, it will return the response
            of both of these methods. The final value returned is the status
            of the POST grades request"""

        new_assignment = self.post_assignment(section_id, assignment_name,
                                              assignment_date,
                                              total_marks_possible,
                                              category_id, grading_scale_id)
        assignment = new_assignment[u'id']
        response = self.post_grades(section_id, assignment,
                                     student_ids_and_grades_list)
        return assignment

    # ==============
    # = Attendance =
    # ==============

    @qs.clean_arg
    def post_attendance(self, student_id, teacher_id, date, status, remarks='',
            description='', **kwargs):
        """POST attendance via the /attendance API method.

        Status codes:
            Present: P
            Absent: A
            Tardy: T
            Absent with excuse: EA
            Tardy with excuse: ET

        Note that remarks are the notes taken normally via the GUI.
        """
        teacher_id = qs.clean_id(teacher_id)
        request = self._request(
            'POST attendance data by date/student',
            '/students/{}/attendance/{}'.format(student_id, date),
            **kwargs)
        request.verb = qs.POST
        request.request_data = {
            'status': status,
            'teacherId': teacher_id,
            'description': description,
            'remarks': remarks,
        }
        return self._make_request(request, **kwargs)

    # ================
    # = Report Cards =
    # ================

    @qs.clean_arg
    def get_report_card(self, student_id, report_cycle_id=None, **kwargs):
        """GET the report card for a given student. Defaults to the active
        report cycle.

        Returns:
            Dict of report card data, like so:
            {
                'reportCardLevel': {
                    'report-date': '1234',
                    ...
                },
                'sectionLevel': {
                    '{sectionId}': {
                        'marks': '100',
                        ...
                    },
                    ...
                }
            }
        """
        cache = self._report_card_cache
        if report_cycle_id is None:
            report_cycle_id = self.get_active_report_cycle()['id']

        kwargs['cache_filter'] = {
            'reportCycleId': report_cycle_id,
            'studentId': student_id
        }

        cache_id = self._rc_id_for_cache(student_id, report_cycle_id)
        if _should_make_request(cache, **kwargs):
            uri = '/students/{}/reportcards/{}'.format(
                student_id,
                report_cycle_id)
            request = self._request(
                'GET a report card by student and report cycle',
                uri,
                **kwargs)
            rc = self._make_request(request, **kwargs)
            rc['studentId'] = student_id
            rc['reportCycleId'] = report_cycle_id
            rc['_qstools_id'] = cache_id
            self._report_card_cache.add(rc)
        return cache.get(cache_id, **kwargs)

    def get_report_cycles(self, **kwargs):
        """GET all report cycles, which are then used to get report cards."""
        cache = self._report_cycle_cache
        if _should_make_request(cache, **kwargs):
            request = self._request('GET all report cycles',
                '/reportcycles',
                **kwargs)
            cache.add(self._make_request(request, **kwargs))
        return cache.get(**kwargs)

    def get_active_report_cycle(self):
        """GET the active report cycle"""
        rc_cycles = self.get_report_cycles()
        return [i for i in rc_cycles if i['isActive'] is True][0]

    @qs.clean_arg
    def post_report_card_section_level(self, student_id, report_cycle_id,
            section_level_data, **kwargs):
        """POST section or criteria-level report card data.

        The section_level_data should be a dict in this format:
        {
            "section_id": {
                "values": {
                    "marks": "110",
                    "grade": "A++",
                }
            },
            ...
        }

        This currently doesn't support criteria, but probably will.
        """
        report_cycle_id = qs.clean_id(report_cycle_id)
        request_data = {
            'sectionLevel': json.dumps(section_level_data)
        }

        url = '/students/{}/reportcards/{}'.format(student_id, report_cycle_id)
        request = self._request('POST section-level rc data', url, **kwargs)
        request.verb = qs.POST
        request.request_data = {
            'sectionLevel': json.dumps(section_level_data)
        }

        response = self._make_request(request, **kwargs)
        if request.successful:
            cache_id = self._rc_id_for_cache(student_id, report_cycle_id)
            self._report_card_cache.invalidate()
        return response

    # ===============
    # = Transcripts =
    # ===============

    @qs.clean_arg
    def get_transcript(self, student_id, **kwargs):
        """GET transcript for a student id"""
        cache = self._transcript_cache
        kwargs['identifier'] = student_id
        if _should_make_request(cache, **kwargs):
            request = self._request(
                'GET transcript for a student id',
                '/transcripts/{}'.format(student_id),
                **kwargs)
            transcript = self._make_request(request, **kwargs)
            transcript['studentId'] = student_id
            cache.add(transcript)
        return cache.get(**kwargs)

    @qs.clean_arg
    def post_transcript_section_level(self, student_id, section_level_data, **kwargs):
        """POST transcript semester data for a given student and section. 
        Student ID, Semester ID, Section ID and marks are required.

        The section_level_data should be in this format:
        {'sectionId': {'values': {'identifier1': 'value1',
                                    'identifier2': ...}},
        'sectionId': ...}

        """
        student_id = qs.clean_id(student_id)
        # section_id = qs.clean_id(section_id)

        url = '/transcripts/{}'.format(student_id)
        request = self._request('POST section-level Transcript data', url, **kwargs)
        request.verb = qs.POST
        request.request_data = {
            'sectionLevel': json.dumps(section_level_data)
        }

        return self._make_request(request, **kwargs)

    # ================
    # = Fee Tracking =
    # ================

    @qs.clean_arg
    def post_fee(self, student_id, category, amount, date, description='', **kwargs):
        """POST a charge to a student's profile via the Fee Tracking API,
        which is documented on Assembla #2210.

        Args:
            student_id: The student the charge is for.
            amount: a number for the dollar amount of the charge. Make amount
                negative to post a payment.
            date: PlainDate of the charge, e.g. '2014-05-25'
            description (optional): charge description.
            fee_type: Either 'C' for charge or 'P' for Payment
        """
        amount = qs.finance_to_float(amount)
        fee_type = 'C'
        if amount < 0:
            fee_type = 'P'
            amount = (0 - amount)
        request = self._request(
            'POST charge',
            '/students/{}/fees'.format(student_id),
            **kwargs)
        request.verb = qs.POST
        request.request_data = {
            'feeCategoryId': category,
            'date': date,
            'description': description,
            'amount': amount,
            'feeType': fee_type
        }
        return self._make_request(request, **kwargs)

    # ==============
    # = Discipline =
    # ==============

    @qs.clean_arg
    def post_incident(self, student_id, teacher_id, detail, date,
            demerit_points=1, **kwargs):
        """POST a discipline incident, using the /incidents API from #2209.

        Args:
            student_id: The student the incident is for - "Student" in the GUI.
            teacher_id: The teacher that reported the incident - "Reported By".
            detail: The detail string of what occurred - "Incident detail".
            date: A date string of the date it occurred in YYYY-MM-DD format -
                "Incident date".
            demerit_points: The demerit points applied (optional) - "Demerit
                Points".
        """
        teacher_id = qs.clean_id(teacher_id)

        request = self._request('POST a discipline incident',
            '/incidents',
            **kwargs)
        request.verb = qs.POST
        teachers_by_id = self.get_teachers(by_id=True, fields='userId')
        user_id = teachers_by_id[teacher_id]['userId']
        request.request_data = {
            'date': date,
            'detail': detail,
            'demeritPoints': demerit_points,
            'teacherId': teacher_id,
            'studentId': student_id,
            'userId': user_id
        }
        return self._make_request(request, **kwargs)

    # =============
    # = Protected =
    # =============

    def _request(self, *args, **kwargs):
        """Return a base request to use.

        Returns either QSRequest or a subclass based on self.server
        """
        request_class = {
            'live': qs.QSRequest,
            'backup': qs.QSBackupRequest,
            'local': qs.QSLocalRequest
        }[self.server]
        return request_class(*args, **kwargs)

    def _make_request(self, request, **kwargs):
        """Process any QSRequest in this class and make it.

        Args:
            request: the prepared (but not yet made) QSRequest
            kwargs: the **kwargs passed to the function that
                instantiated this request, such as self.get_students().
        Returns:
            The data from the completed request

        # TODO make silent a valid kwarg
        """
        request.set_api_key(self.api_key)
        critical = kwargs.get('critical')
        fields = kwargs.get('fields')

        if critical:
            request.critical = kwargs['critical']

        if fields:
            if str(fields) == fields:
                fields = [fields]
            request.fields += fields

        request.make_request()

        if request.successful:
            qs.api_keys.set(self._api_key_store_key_path(), self.api_key)
        return request.data

    @qs.clean_arg
    def _make_single_request(self, identifier, base_uri, request_all_method,
            request_description, **kwargs):
        """Make a single request to a resource that has both a method to
        request all and a method to request a single resource. Handles both
        the request part and caching part.

        Resources are such as /students/{studentID}, the single version of
        /students.

        Args:
            identifier: The id to be passed to the API in the URL, such as
                the student id.
            base_uri: The base URI of the the resource, such as '/students'.
            request_all_method: The method used to request all of the resource,
                such as self.students.
            request_description: The description to include in the request,
                such as 'GET student by id'.
            kwargs: The kwargs from the source method.
        """
        cached = request_all_method(by_id=True, **kwargs).get(identifier)
        if cached:
            return cached
        else:
            request = self._request(
                request_description,
                '{}/{}'.format(base_uri, identifier),
                **kwargs)
            return self._make_request(request, **kwargs)

    def _parse_access_key(self):
        """Parses self._access key, which could be a schoolcode or API key, and
        set self.schoolcode and self.api_key.
        """
        # api keys are like schoolcode.blahblahblah
        match = re.match(r'(.+)\.', self._access_key)
        if match:
            self.schoolcode = match.groups()[0]
            self.api_key = self._access_key
        else:
            self.schoolcode = self._access_key
            self.api_key = qs.api_keys.get(self._api_key_store_key_path())

    def _api_key_store_key_path(self):
        return ['qs', self.server, self.schoolcode]

    def _enrollment_dict(self, student):
        student_id = student.get('id') or student.get('smsStudentStubId')
        return {
            'id': student_id,
            'smsStudentStubId': student_id,
            'fullName': student['fullName'],
        }

    def _update_section_enrollment_cache(self, **kwargs):
        """Update the section enrollments cache based on the /students
        endpoint. This only updates the cache for the current semester.
        """
        cache = self._section_enrollment_cache
        if _should_make_request(cache, **kwargs):
            students = self.get_students(fields='smsClassSubjectSetIdList')
            section_enrollments = {}

            for student in students:
                for section_id in student['smsClassSubjectSetIdList']:
                    if section_id not in section_enrollments:
                        section_enrollments[section_id] = []
                    section_enrollments[section_id].append(
                        self._enrollment_dict(student)
                    )
            for section in self.get_sections():
                section_id = section['id']
                if section_id not in section_enrollments:
                    section_enrollments[section_id] = []

            enrollment_list = [
                {'id': k, 'students': v}
                for k, v in section_enrollments.iteritems()
            ]
            cache.add(enrollment_list)

    def _rc_id_for_cache(self, student_id, report_cycle_id):
        return qs.make_id(student_id, report_cycle_id)

    def _assignments_with_grades(self, **kwargs):
        """Add the the 'grades' key to each assignment in assignments.
        Returns a copy of assignments with the 'grades' key inserted."""
        by_id = kwargs.get('by_id')
        assignments = copy.deepcopy(self._assignment_cache.get(**kwargs))

        if by_id is True:
            assignments = qs.dict_to_dict_list(assignments)
        for assignment in assignments:
            assignment['grades'] = self.get_grades(
                assignment['sectionId'],
                assignment['id'])
        if by_id is True:
            assignments = qs.dict_list_to_dict(assignments)
        return assignments


def _should_make_request(cache, **kwargs):
    """Whether or not a new QS API request should be made, based on cache
    status and kwargs.
    """
    use_cache = kwargs.get('use_cache')
    fields = kwargs.get('fields')
    cache_filter = kwargs.get('cache_filter')

    if use_cache is False:
        return True
    elif fields and cache.has_fields(fields) is False:
        return True
    elif cache.get(**kwargs) is None:
        return True
    return False

# -*- coding: utf-8 -*-
"""
This module defines and runs functions which scrape the 5 College course
catalogs to create a file, data.json, which plugs
into the Oxford Internet Institute's interactive network viewer.  This
file contains the node and edge attributes of the network of prerequisites
at each college: which courses are required by which.

Created on Sat Mar 19 15:43:59 2016

@author: steven
"""

# import block
import shutil
from lxml import html
import urllib3 as ul
ul.disable_warnings()
HTTP = ul.PoolManager()
import io
#import time
import re
import itertools
from datetime import date
import igraph
import json
import os
from random import randint
from collections import OrderedDict
#%%
def get_dept_code(string):
    "takes a course code and returns the department code"
    tmp = string.split('-')
    return('-'.join(tmp[:len(tmp) - 1]))

def get_semester():
    "Gets the date, and returns the next semester to scrape, F or S"
    month = date.today().month
    if month in [11, 12, 1, 2, 3]:
        return('S')
    else:
        return('F')

def get_year():
    "returns the year of the most recent posted semester."
    now = date.today()
    if now.month in [11, 12]:
        return(now.year + 1)
    else:
        return(now.year)

def get_institution_course_urls(year=None, semester=None):
    """
    This function returns a list of institutions' current course
    offerings' course page urls as current_catalog_urls, a list
    Args:
        Year: int year
        Semester: 'F' or 'S'
    Returns:
        institution_course_codes : a dict of institutions first letters (i.e.
            U, M, A, S, H), mapping to dicts of institutions' course codes to
            their most recent url.
    """
    # define dict to be returned if none supplied
    institution_course_codes = {
        # a dict of lists of unique course codes at each institution
        "U" : {},
        "M" : {},
        "A" : {},
        "S" : {},
        "H" : {}
        }
    if semester == None:
        semester = get_semester()
    if year == None:
        year = get_year()
    
    # define address strings
    query_url = "https://www.fivecolleges.edu/academics/courses?" + \
    "field_course_semester_value={semester}&" + \
    "field_course_year_value={year}&" + \
    "field_course_institution_value%5B%5D={institution}&" + \
    "title=&" + \
    "course_instructor=&" + \
    "body_value=&" + \
    "field_course_number_value=&" + \
    "field_course_subject_name_value=&" + \
    "field_course_subject_value="
    next_page_link_xpath = '//*[@class="pager-next"]/a/@href' #tested; works
    courses_table_row_xpath = '//*[@class="view-content"]/' + \
    'table["views-table sticky-enabled cols-7 ' + \
    'tableheader-processed sticky-table"]/tbody/tr'
    # define the dict to be returned

    # get all catalog pages' info
    for institution in institution_course_codes.keys():
        url = query_url.format(semester=semester,
                               year=year,
                               institution=institution)
        data = HTTP.request("GET", url).data
        tree = html.parse(io.BytesIO(data))
        last_page = False
        while last_page == False:
            if tree.xpath(next_page_link_xpath) == []:
                last_page = True
            else: 
                next_url = 'https://www.fivecolleges.edu/' + \
                tree.xpath(next_page_link_xpath)[0]
            course_rows = tree.xpath(courses_table_row_xpath)
            for course_row in course_rows:
                tmp = OrderedDict()
                row_elements = [i.text for i in course_row]
                tmp["title"] = course_row[4].xpath('./a/text()')[0]
                tmp["url"] = 'https://www.fivecolleges.edu' + \
                        course_row[4].xpath('./a/@href')[0]
                tmp["date"] = '{}{}'.format(year, semester)
                code = '-'.join([i.strip() for i in row_elements[0:2]])
                institution_course_codes[institution][code] = tmp
            data = HTTP.request("GET", next_url).data
            tree = html.parse(io.BytesIO(data))
    return institution_course_codes
    
def get_course_description(institutions, new_courses):
    """
    This function adds course description information to the dict
    institution_course_codes
    Args:
        institutions : a dict mapping each institution to codes,
            which in turn map to dicts of course details.
        new_courses: a dict mapping each institution to codes, which in turn
            map to dicts containing urls and titles of courses
    Returns:
        institution_course_codes: institutions dict, with added course details
    """
    for institution in new_courses.keys():
        print(institution)
        left = len(new_courses[institution])
        counter = 0
        for course in new_courses[institution].keys():
            entry = OrderedDict()
            for i in new_courses[institution][course]:
                entry[i] = new_courses[institution][course][i]
                # title, url, date
            url = new_courses[institution][course]["url"]
            data = HTTP.request("GET", url).data
            tree = html.parse(io.BytesIO(data))
            tmp = tree.xpath('//*[@class="field-item even"]/text()')
            if institution == 'A':
                tmp += tree.xpath('//*[@class="field-item even"]/p/text()')
            dept = tmp[2]
            tmp = '\n'.join(tmp)
            entry["department"] = dept
            entry["description"] = tmp
            institutions[institution][course] = entry
            counter += 1
            if (left - counter) % 100 == 0:
                print(left - counter)
    return(institutions)

def make_dept_code_mapping(catalog_dict):
    "extracts the dept codes and dept names from the course catalog"
    mapping = []
    for course_code_str in catalog_dict.keys():
        dept_code = get_dept_code(course_code_str)
        dept = catalog_dict[course_code_str]['description'].split('\n')[2]
        mapping.append((dept_code, dept))
    return(list(set(mapping)))
    # looks like umass uses hyphenated dept codes, like COMM-DIS or ART-HIST
    
def replace_dept_strings(string, mapping):
    "replaces a string specifying a department with the department code"
    for code, dept in mapping:
        if dept in string:
            string = string.replace(dept, code)
    return(string)

def get_prereqs(catalog_dict):
    """
    This function creates a dictionary, prereqs, mapping each course code to
    the required courses it names in its  online course description.
    Args:
        catalog_dict: a dict mapping all the codes in a university's course
            catalog to course details
        marker: a list of strings marking the starting point of the sentence in
          a course's description containing the codes of the course's prereqs.
    Returns:
        prereqs: a list of edge tuples (code of course required, code of course
        requiring)
    """
    req_strings = ['requisite', 'Requisite', 'Prerequisite', 'Pre Req',
                   'prereq', 'Prereq', 'prerequisite']
    prereqs = []
    dept_codes = [get_dept_code(cnum) for cnum in catalog_dict.keys()]
    nums = []
    for cnum in catalog_dict.keys():
        nums += cnum.split('-')[len(cnum.split('-')) - 1:len(cnum.split('-'))]
    mapping = make_dept_code_mapping(catalog_dict)
    
    # search the line describing requirements for course codes
    for cnum in catalog_dict.keys():
        desc = catalog_dict[cnum]["description"] # a string
        desc = replace_dept_strings(desc, mapping)
        req_line = ''
        if len(desc) > 0:
            desc = desc.replace(u'\xa0', u' ')
            sentences = [i for i in re.split('\n|\.', desc)]
            for i in sentences:
                for j in req_strings:
                    if j in i:
                        req_line += i + ' '
            words = re.split(' |-|,|/|;|\.', req_line)
            current_dept = get_dept_code(cnum)
            # ^ assume a course is most likely to require another in its own
            # department
            for word in words:
                if word in dept_codes:
                    current_dept = word
                if word in nums:
                    prereqs.append((current_dept + '-' + word, cnum))
        catalog_dict[cnum]["prereqs"] = req_line
    return(prereqs)

def test_prereqs(prereqs_edgelist, course_details):
    """
    This function tests the edgelist of prereq relationships, displaying lines
    explaining requirements which do not contain any course numbers
    Args:
        prereqs_edgelist: a list of tuples mapping course numbers AT AN
            INSTITUTION to the codes of their prerequisites
        course_details: a list of tuples mapping course numbers AT AN
            INSTITUTION to a dict of its details
    Returns:
        nuthin'; prints any places where there should be prereqs but there are
        none detected.
    """
    counter = 0
    for code in course_details.keys():
        if code not in itertools.chain(*prereqs_edgelist):
            if len(course_details[code]["prereqs"]) > 0:
                counter += 1
                #print(code)
                #print(course_details[code]["prereqs"])
    print(counter)
    
def make_course_graph(course_details, prereqs_edgelist):
    """
    Makes an igraph Graph object, complete_course_graph, from the edgelist of
    prerequisite relations and the total number of courses and makes the
    object global.
    Args:
        course_details: a dict mapping course numbers AT AN INSTITUTION to a
            dict of its details
        prereqs_edgelist: a list of edge tuples mapping course numbers AT AN
            INSTITUTION to the codes of its prerequisites
    Returns:
        a directed acyclic igraph object representing all the requirement
        relations at one institution
    """
    # count the number of required courses not in 'course_details'
    all_courses = itertools.chain(*prereqs_edgelist)
    extra_courses = [c for c in all_courses if c not in course_details.keys()]
    number_of_courses = len(extra_courses) + len(course_details)

    # create an empty graph with all the courses as nodes, then add prereq
    # relations from the prereqs edgelist
    names_of_courses = list(course_details.keys()) + extra_courses
    complete_course_graph = igraph.Graph(number_of_courses, directed=True)
    complete_course_graph.vs["name"] = names_of_courses
    complete_course_graph.add_edges(prereqs_edgelist)
    return(complete_course_graph)

def make_subgraph(dept_string, course_graph):
    """
    takes a department string, and finds all courses in this department or
    required by the department, and create a new igraph object from these
    courses and their relationships.
    Args:
        dept_string: a string specifying a department code
        prereqs_edgelist: a list of tuples mapping course codes to the codes
            of their prerequisites at an institution
        complete_course_graph: an igraph object of all the prerequisite
            relations at that institution
    Returns:
        all courses in the department and their prereqs/the courses that
        require them
    """
    # get a list of courses relevant to the department
        
    relevant_courses = []
    for i in enumerate(course_graph.vs["name"]):
        if get_dept_code(i[1]) == dept_string:
            relevant_courses.append(i)
    neighbors = course_graph.neighborhood([i[0] for i in relevant_courses])
    relevant_courses = list(set(itertools.chain(*neighbors)))
    return(course_graph.induced_subgraph(relevant_courses))

def get_sugiyama_layout(subgraph):
    """
    This function sorts a prerequisites graph into 100,200,300, and 400-level
    classes, then returns the x and y positions of each node in that layout
    Args:
        subgraph: a graph of course prerequisite relations with course codes as
            vertex names
    Returns:
        a list of tuples specifying x and y coordinates of each node in the
        graph in a sugiyama layout for directed acyclic graphs.
    """
    sugiyama_layout = subgraph.layout_sugiyama(maxiter=1000)
    sugiyama_layout = sugiyama_layout[0:subgraph.vcount()]
    return sugiyama_layout

def get_rgb():
    "returns a tuple of three numbers between 0 and 255"
    return ((randint(0, 255), randint(0, 255), randint(0, 255)))

def make_json(dept_string, course_details, complete_course_graph):
    """
    This function makes a JSON object called 'data', to be inserted
    into the directory exported by a sigma.js template to
    make an interactive web visualization of the prereqs network
    Args:
        dept_string: a string specifying a department at an institution
        course_details: a dict mapping course codes to course details at an
            institution
        complete_course_graph: a directed igraph object containing all the
            courses at the institution as nodes and all the requirements of
            each course as the first-order in-neigbhors of the course
    Returns:
        data: a  JSON file specifying the nodes and edges to be drawn by
            sigma.js and the information about nodes to display.
    """
    data = {"edges":[], "nodes":[]}

    #get the subgraph, node positions
    subgraph = make_subgraph(dept_string, \
                             complete_course_graph)
    sugiyama_layout = get_sugiyama_layout(subgraph)

    unique_departments = [get_dept_code(name) for name in subgraph.vs["name"]]
    department_colors = {dept:get_rgb() for dept in unique_departments}

    for node in enumerate(subgraph.vs["name"]):
        if node[1] in course_details.keys():
            node_output = OrderedDict()
            node_output["label"] = node[1]
            node_output["x"] = sugiyama_layout[node[0]][0]
            node_output["y"] = sugiyama_layout[node[0]][1]
            node_output["id"] = str(node[0])

            attrs = OrderedDict()
            attrs["Title"] = course_details[\
                node[1]]["title"]
            attrs["Description"] = course_details[node[1]]["description"]
            attrs["Department Code"] = get_dept_code(node[1])
            attrs["Course Site"] = \
                "<a href= '" + \
                course_details[node[1]]["url"] + \
                "'> Course Site </a>"
            attrs["Requisite"] = course_details[node[1]]["prereqs"]
            node_output["attributes"] = attrs

            node_output["color"] = 'rgb' + \
                str(department_colors[get_dept_code(node[1])])
            node_output["size"] = 10.0
        # if the course has no retrieved details:
        else:
            node_output = OrderedDict()
            node_output["label"] = node[1]
            node_output["x"] = sugiyama_layout[node[0]][0]
            node_output["y"] = sugiyama_layout[node[0]][1]
            node_output["id"] = str(node[0])
            node_output["attributes"] = OrderedDict()
            node_output["attributes"]["Title"] = node[1]
            node_output["attributes"]["Description"] = 'not offered in the' + \
                " last 4 semesters"
            node_output["attributes"]["Department Code"]=get_dept_code(node[1])
            node_output["attributes"]["Course Site"] = ""
            node_output["attributes"]["Requisite"] = ''
            node_output["color"] = 'rgb' + \
                str(department_colors[get_dept_code(node[1])])
            node_output["size"] = 10.0
        data["nodes"].append(node_output)

    edgelist = subgraph.get_edgelist()
    for edge in enumerate(edgelist):
        color = department_colors[get_dept_code(subgraph.vs["name"][edge[1][1]])]
        color = 'rgb' + str(color)
        edge_output = OrderedDict()
        edge_output["label"] = ''
        edge_output["source"] = str(edge[1][0])
        edge_output["target"] = str(edge[1][1])
        edge_output["id"] = str(len(node_output) - 1 + 2*edge[0])
        #                                        ^ this is to conform with the
        # odd indexing I see in working visualisations
        edge_output["attributes"] = {}
        edge_output["color"] = color # target node color
        edge_output["size"] = 1.0
        data["edges"].append(edge_output)
    return data

def find_or_make_directory_address(inst_code, dept_string):
    """
    finds whether there is a directory named after a deptarment string, and
    if not, makes one
    Args:
        inst_code: U for UMass, A for Amherst, etc.
        dept_string: a string specifying a department at an institution
    Returns:
        a string specifying an directory
    """
    directory = './{}/{}'.format(inst_code, dept_string)
    if not os.path.exists(directory):
        shutil.copytree('../AmherstGraph/NetworkTemplateWithoutData_JSON',
                        directory)
    return directory

def export_json(inst_code, dept_string, course_details, complete_course_graph):
    """
    writes the data json object describing a major's prerequisite network to
    a file called 'data.json' in a directory named after the department
    Args:
        inst_code: U for UMass, A for Amherst, etc.
        dept_string: a string specifying a department at an institution
        course_details: a dict mapping course codes to course details at an
            institution
    Returns:
        None
    """
    data = make_json(dept_string, course_details, complete_course_graph)
    path = find_or_make_directory_address(inst_code, dept_string)
    path += '/data.json'
    json_file = json.dumps(data, separators=(',', ':'))
    target_file = open(path, 'w')
    target_file.write(json_file)
    target_file.close()

#%% run the code
if __name__ == "__main__":
    T = open('PriorCourseDetails.json')  # for temp
    INST = json.loads(T.read())
    T.close()
    # add the new semester's data; make sure to run each semester
    NEW_COURSES = get_institution_course_urls()
    #rebuild INST entirely
#    for i in [(2015, 'S'), (2014, 'F'), (2014, 'S')]:
#        TEMP =  get_institution_course_urls(year=i[0],
#                                            semester=i[1])
#        for i in TEMP:
#            if i not in NEW_COURSES:
#                NEW_COURSES[i] = TEMP[i]
#    INST = {
#        # a dict of lists of unique course codes at each institution
#        "U" : {},
#        "M" : {},
#        "A" : {},
#        "S" : {},
#        "H" : {}
#        }
    INST = get_course_description(INST, NEW_COURSES)
    T = open('PriorCourseDetails.json', 'w')
    T.write(json.dumps(INST, separators=(',', ':')))
    T.close()
    print('Nearly there...')
    for key in INST.keys():
        DEPTS = list(set([get_dept_code(key) for k in INST[key].keys()]))
        PREREQS = get_prereqs(INST[key])
        test_prereqs(PREREQS, INST[key])
        print('^TESTING PREREQS; # courses missing prereqs')
        COURSE_GRAPH = make_course_graph(INST[key], PREREQS)
        for dept_str in DEPTS:
            export_json(key, dept_str, INST[key], COURSE_GRAPH)
            print(dept_str + ' done')
    print(""" That's all folks! """)

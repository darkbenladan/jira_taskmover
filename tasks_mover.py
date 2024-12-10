# -*- coding: utf-8 -*-

import logging
import sys
import argparse
import requests
import time
import json
import os
import threading
from datetime import datetime, date, timezone, timedelta
from requests.auth import HTTPBasicAuth
import collections
#for sending mails
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import socket

#Create logger
def create_logger(logfile, loglevel):
    '''
    Standard method used for creating logger,
    by default the logger is not writing to file
    
    Args:
        logfile (str): name of the file where to write  - not used
        loglevel (str): level of logging
    Returns:
        logger object
    '''
    log = logging.getLogger(__name__)
    log.setLevel(loglevel)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(loglevel)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    return log

def create_argparser():
    '''
    Funtion to create arg parser used by script

    Returns:
        argparse parsed script paramters translated into variables
    '''
    parser = argparse.ArgumentParser(description='Overdue task mover. Python program for moving JIRA tasks with overdue dates')
    parser.add_argument("--loglevel", help='Set loglevel for this script, default INFO', default='DEBUG')
    parser.add_argument("--jiraurl", help='URL to JIRA server', default='jira_url')
    parser.add_argument("--movetasks", help='Flag - move dates or just send list of overdue', action='store_true')

    args = parser.parse_args()
    return args

# one important thing: if we cannot find variables with user\pass in bamboo globals for KEY -
# to have an ability to update tasks date we'll assign user and pass for GW and try to do that by GW user
prj_filters_dict = {
    'Kanban_name'         : {'FilterID':'FilterID', 'user':'', 'pass':''}
}


def call_jira_api(type,url,user_name,user_password, req_data=""):
    log.info("performing request to: "+url+" request type "+type)
    payload={}
    if type == "POST" or type == "PUT":
        payload = req_data.encode('utf-8')
        
    headers = {
        "Accept" : "*/*",
        "Content-Type": "application/json",
        "X-Atlassian-Token": "no-check",
        }
        #        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36"
    try:
        #if type == "POST":
        #     response = requests.request(type, url, json=payload, headers=headers, auth=HTTPBasicAuth(user_name, user_password), verify=False)
        #else:
        response = requests.request(type, url, data=payload, headers=headers, auth=HTTPBasicAuth(user_name, user_password), verify=False)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        log.warning("timeout occured for url:"+url)
        return [None,-2]
    except requests.exceptions.ConnectionError as ex:
        print (ex)
        log.warning("remote server refuesed connection "+url)
        return [None,-1]
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        print (e)
        if status_code == 403:
            log.warning("http 403 error occured")
            return [None,-403]
    return [response,None]

def read_params_from_env():
    '''Method used to read paramters from environment vars and update our predefined dict with logins and passwords 
    method is getting all env vars that contains value of filter_to_match variable
    eg.
    example_user=devops
    example_password=password
    
    searching in variables names list by key (GW or other)
    and updates correct dict entry, for example 
    'GW' :  {'FilterID':'FilterID', 'user':'', 'pass':''} , 

    We could not use that, but in such case we should keep passwords in opened form and with such script - nope
    In last part of function we checking every dict key and if it's not updated - overriding it by GW entry
    '''
    filter_to_match = "_devops_"
    bamboo_var_prefix = "bamboo.variable."
    bamboo_env_dict = {}
    bamboo_env_dict=os.environ
    # below lambda expression is used to pick all elements that have "_devops_" in the env var name
    # after that we should have only pairs like {{example_user, value},{example_password,value}, ...}
    credent_env_dict = dict(filter(lambda element: filter_to_match in element[0], bamboo_env_dict.items()))

    #updating data for filters dict
    for ekey,evalue in credent_env_dict.items():
        for key in prj_filters_dict:
            #here we found for env values 
            if key in str(ekey).upper():
                #variable with name "KEY_devops_user"
                if str(ekey).endswith("_user"):
                    prj_filters_dict[key]['user']=str(evalue)
                    print("Found OS variable: " + "user: " +  str(ekey) + " with value: " + str(evalue))
                elif str(ekey).endswith("_password"):
                    prj_filters_dict[key]['pass']=str(evalue)
                    print("Found OS variable: " + "pass: " +  str(ekey) + " with value: No-no-no :)")
                else:
                    print("Found strange OS variable: " + str(ekey))
    
    #checking our dict and updating it if needed by default user and pass
    for key in prj_filters_dict:
        if prj_filters_dict[key]['user'] == '':
            print("'Haven't found user and pass for key: " + str(key) + " in Bamboo global variables. Assigning default - GW")
            prj_filters_dict[key]['user']=prj_filters_dict['GW']['user']
            prj_filters_dict[key]['pass']=prj_filters_dict['GW']['pass']

def read_params_from_env_gitlab():
    filter_to_match = "DevOps_tasks"
    devops_user = os.getenv("DevOps_tasks_USER")
    devops_password = os.getenv("DevOps_tasks_PASSWORD")

    if devops_user:
        prj_filters_dict['DevOps_tasks']['user'] = devops_user
        print("Found GitLab variable: DevOps_tasks_USER with value:", devops_user)
    else:
        print("Haven't found user for key: DevOps_tasks in GitLab environment variables. Using default - GW")

    if devops_password:
        prj_filters_dict['DevOps_tasks']['pass'] = devops_password
        print("Found GitLab variable: DevOps_tasks_PASSWORD with value: No-no-no :)")
    else:
        print("Haven't found pass for key: DevOps_tasks in GitLab environment variables. Using default - GW")

#function for debug
def prj_filters_dict_print():
    print("Printing filters dict for debug:")
    for key in prj_filters_dict:
        print ("Key: " + str(key) + "    Filter: " + prj_filters_dict[key]['FilterID'] + "   User: " + prj_filters_dict[key]['user'])

#function for getting lists of JIRA tsks in our team filters
def get_jira_tasks_lists(jira_url, filterId, jira_user,jira_pass):
    jira_filter_rest = jira_url+'/rest/api/2/filter/'+filterId
    jira_filter_raw = call_jira_api("GET",jira_filter_rest,jira_user,jira_pass)    
    #as we could get empty answer - we'll just return empty dict
    jf_tasks={}
    try:
        jf_json = jira_filter_raw[0].json()
        jf_jql = jf_json['jql']

        #now we have filter that used for our Kanban board for current project
        #log.info("Got that JQL for provided filter ID: " + jf_jql)

        #using filter to get query for list of tasks with only needed fields: assignee, status, dueDate
        jira_query= '''{
            "jql": %s,
            "startAt": 0,
            "maxResults": 250,
            "fields": [
                "summary",
                "status",
                "assignee",
                "duedate",
                "key"
            ]
        }''' % json.dumps(jf_jql) #.format(jf_jql)

        #log.info("Result JSON for JQL search query: " + jira_query)

        #Query JIRA to get list of tasks
        #jf_tasks_raw = call_jira_api("POST",jira_filter_rest,jira_user,jira_pass,jira_query)
        jira_search_rest = jira_url+'/rest/api/2/search'
        jf_tasks_raw = call_jira_api("POST",jira_search_rest,jira_user,jira_pass,jira_query)

        if jf_tasks_raw[0] != None:
            jf_tasks = jf_tasks_raw[0].json()
        else:
            print ("Can't get tasks for filter ID: " + str(filterId) + " with error: " + jf_tasks_raw[1])
    except:
        #We cannot get task list by any reason. Printing info and return empty list
        print("By any reason cannot get task list for filter ID: " + str(filterId))
        #assign empty list as we need to get it later
        jf_tasks['issues'] = []
        
    return jf_tasks

def get_overdue_tasks(jira_url):
    jira_tasks = {}

    # get current date in the format JIRA uses
    today = date.today()
    print("Today is: " + today.strftime('%Y-%m-%d'))

    statuses_fltr = ['готово', 'обработано', 'ready', 'закрыто', 'закрыт', 'решен', 'mvp', 'canceled', 'cancelled', 'выполнено', 'готово', 'closed', 'done', 'confirmed']

    for k, t in prj_filters_dict.items():
        jira_tasks[k] = get_jira_tasks_lists(jira_url, t['FilterID'], t['user'], t['pass'])['issues']
        if jira_tasks[k] is None:
            jira_tasks[k] = get_jira_tasks_lists(jira_url, prj_filters_dict['GW']['FilterID'], prj_filters_dict['GW']['user'], prj_filters_dict['GW']['pass'])['issues']

    overdue_tasks = {}
    for key in jira_tasks:
        overdue_tasks[key] = []
        for item in jira_tasks[key]:
            try:
                status_name = item['fields']['status']['name'].lower()
                duedate = item['fields']['duedate']
                if duedate is not None and status_name not in statuses_fltr and datetime.strptime(duedate, '%Y-%m-%d').date() <= today:
                    overdue_tasks[key].append(item)
            except (KeyError, ValueError):
                pass  # Handle any potential missing keys or date conversion errors

    return overdue_tasks


def is_weekend(date_obj):
    return date_obj.weekday() >= 5  # Saturday and Sunday are 5 and 6

def next_working_day(date_obj):
    while is_weekend(date_obj):
        date_obj += timedelta(days=1)
    return date_obj


def move_overdue_tasks(jira_url, tasks_list):
    not_moved_jira_tasks = {}

    # Define a function to calculate the next working day
    def next_working_day(date_obj):
        while is_weekend(date_obj):
            date_obj += timedelta(days=1)
        return date_obj

    new_due_date = next_working_day(date.today() + timedelta(days=1))

    # URL for updating JIRA issues - '/' at the end is important
    jira_update_rest = jira_url + '/rest/api/2/issue/'

    upd_due_json = '''{
        "fields": {
            "duedate": %s
        }
    }''' % json.dumps(new_due_date.strftime('%Y-%m-%d'))

    # Iterate through tasks and update due dates
    for key in tasks_list.keys():
        not_moved_jira_tasks[key] = []
        problem_items = False
        for item in tasks_list[key]:
            call_result = call_jira_api("PUT", jira_update_rest + item['key'], prj_filters_dict[key]['user'],
                                        prj_filters_dict[key]['pass'], upd_due_json)
            if call_result[0] is None:
                print("Not updated date for issue: " + str(key) + " with error: " + call_result[1])
                not_moved_jira_tasks[key].append(item)
                problem_items = True
                print("Will be using GW user")
                call_result = call_jira_api("PUT", jira_update_rest + item['key'], prj_filters_dict['GW']['user'],
                                            prj_filters_dict['GW']['pass'], upd_due_json)
        if not problem_items:
            not_moved_jira_tasks.pop(key, None)

    return not_moved_jira_tasks



def sendMailOverdue(tasks_list, problem_tasks_list):
    hostname = str(socket.gethostname())
    sender_email = "bamboo@%s" % hostname
    receiver_email = ["example@example.ru", "teams_integration"]
    message = MIMEMultipart("alternative")
    message["Subject"] = "Check outdated tasks %s" % str(datetime.today().strftime('%d-%m-%Y'))
    message["From"] = sender_email
    message["To"] = ", ".join(receiver_email)

    # Define HTML content
    html_prefix = """\
    <html>
    <body>
        <p>Всем привет. Вы сами все знаете:<br></p>
        <table style="width:70%" cellspacing="2" cellpadding="10" border="1">
        <caption>Список просроченных заявок на сегодня</caption>
        <tr>
            <th width=5%>№</th>
            <th width=15%>Заявка</th>
            <th width=35%>Описание</th>
            <th width=20%>Ответственный</th>
            <th width=15%>Статус</th>
            <th width=10%>Срок</th>
        </tr>
    """

    html_end_table_overdue = """
        </table>
        <br>
    """

    # We should close HTML tags anyway
    html_ending = """
        </body>
    </html>
    """

    # Creating table body for overdue tasks
    counter = 0
    for key in tasks_list.keys():
        for item in tasks_list[key]:
            counter += 1
            assignee_display_name = item['fields']['assignee']['displayName'] if item['fields']['assignee'] is not None else ""
            status_name = item['fields']['status']['name'] if item['fields']['status'] is not None else ""
            duedate = item['fields']['duedate'] if item['fields']['duedate'] is not None else ""
            print("Issue: " + item['key'] + " '" + item['fields']['summary'] + "' dueDate: " + duedate + " is out of date")
            task_html = '''
            <tr>
                <th>%s</th>
                <th><p><a href="jira_url/%s">%s</a></p></th>
                <th>%s</th>
                <th>%s</th>
                <th>%s</th>
                <th>%s</th>
            </tr>
            ''' % (str(counter),
                   item['key'],
                   item['key'],
                   item['fields']['summary'],
                   assignee_display_name,
                   status_name,
                   duedate)
            html_prefix = html_prefix + task_html

    html_prefix = html_prefix + html_end_table_overdue

    # We should close tags anyway, but with different content
    html_problem_tasks = """
        <table style="width:70%" cellspacing="2" cellpadding="10" border="1">
        <caption>Список заявок, которые не удалось передвинуть</caption>
        <tr>
            <th width=5%>№</th>
            <th width=15%>Заявка</th>
            <th width=35%>Описание</th>
            <th width=20%>Ответственный</th>
            <th width=15%>Статус</th>
            <th width=10%>Срок</th>
        </tr>
    """

    counter_err = 0
    # If we have tasks with not changed date - add them in the end of mail
    if bool(problem_tasks_list):
        for key in problem_tasks_list.keys():
            for item in problem_tasks_list[key]:
                counter_err += 1
                assignee_display_name = item['fields']['assignee']['displayName'] if item['fields']['assignee'] is not None else ""
                status_name = item['fields']['status']['name'] if item['fields']['status'] is not None else ""
                duedate = item['fields']['duedate'] if item['fields']['duedate'] is not None else ""
                print("Issue: " + item['key'] + " '" + item['fields']['summary'] + "' dueDate: " + duedate + " not moved date")
                task_html = '''
                <tr>
                    <th>%s</th>
                    <th><p><a href="jira_url/%s">%s</a></p></th>
                    <th>%s</th>
                    <th>%s</th>
                    <th>%s</th>
                    <th>%s</th>
                </tr>
                ''' % (str(counter_err),
                       item['key'],
                       item['key'],
                       item['fields']['summary'],
                       assignee_display_name,
                       status_name,
                       duedate)
                html_problem_tasks = html_problem_tasks + task_html
        html_problem_tasks = html_problem_tasks + html_end_table_overdue
    else:
        html_problem_tasks = """
            <p>Срок завершения всех заявок успешно обновлен!<br></p>
        """

    # Fully formatted mail
    html_prefix = html_prefix + html_problem_tasks + html_ending

    # Convert both parts to MIMEText objects and add them to the MIMEMultipart message
    part2 = MIMEText(html_prefix, "html")
    message.attach(part2)

    # Send email if we have even one overdue issue
    if counter > 0:
        with smtplib.SMTP(host='int.bimeister.io', port='25') as server:
            server.sendmail(sender_email, receiver_email, message.as_string())




##################################
#start of code
#if __name__ == '__main__':
#    '''
#    workaround to allow documnetation creation with sphinx
#    '''

args = create_argparser()
log = create_logger('log.txt',args.loglevel)

jiraurl=args.jiraurl
type="GET"

#get users logins and passwords from bamboo global variables
read_params_from_env_gitlab()
prj_filters_dict_print()

overdue_list = get_overdue_tasks(jiraurl)

problem_list={}
#for debug we can switch flag in bamboo and just send list without updating dates
if args.movetasks:
    problem_list = move_overdue_tasks(jiraurl,overdue_list)

sendMailOverdue(overdue_list,problem_list)
print("Все задачи выполнены. Скрипт завершает работу.")
sys.exit()
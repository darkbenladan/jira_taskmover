# Script for moving overdue tasks

The script is responsible for checking if in DevOps team kanban-boards we have overdue tasks. 
Script is running from specially created for such tasks Bamboo or another CI\CD tools project DevOps Automation Tools and build-plan on daily basis by trigger 

## Parameters

Parameters required by the script:

parameter|Description|Example
---------|------------|------
loglevel| log level of information published | info debug
jiraurl| set URL for JIRA RestAPI | jira_url
movetasks| if that flag mentioned in script call - script would move tasks, not only get the list | False


## Usage

### Get list of overdue tasks

As we have many Kanban-boards and tracking not only tasks, that assigned directly to us, we need more flexible mechanism to get them
For that purpose in script we have predefined dictionary with keys, associated with distinct Kanban by IDs of filters, used for Kanban creation. 
```json
{
    'Kanban name'         : {'FilterID':'FilterID', 'user':'', 'pass':''},
    'Kanban name'        : {'FilterID':'FilterID', 'user':'', 'pass':''}
}
```

But we cannot know if one our tech user has an access to all that kanbans, so we're trying to get user and pass for every dict entry. We're reading bamboo.environment variables in runtime and filter them by containing a substring "_devops_". 
After that we're searching in their names substrings like our dict KEYs and updating dict entries by found values.
For all KEYs left without values we assign default - like 'Kanban name'. 

Subsequent logic is as follow:
1. Get by FilterID JQL for that filter - to have an ability to make correct JQL query by Jira RestAPI.
  * That allows us always get actual info about required Kanban board exactly as it is presented on it.
2. Make in loop JQL-queries to all JQL filters and get all overdue tasks list
  * them are added into dict like {'GW': {GW-tasks}, 'UFO':{UFO-tasks}, etc}
3. If script running without **--movetasks** flag - just send e-mail with recieved tasks list presented in HTML-formatted table
4. If script has **--movetasks** flag - iterate all overdue tasks list and try to use JIRA RestAPI and linked with that Kanban user\login for every Kanban to update due date
  * If our account hasn't permissions to update task or we got other REST error - add such task in second list - ***problem_list***
5. Send e-mail with table of all overdue tasks and second table, that contains tasks that we didn't move by any error

### Bamboo build
In bamboo our build has the job with only two tasks: 
1. Source Code checkout
2. Script execution
```bash
python3 scripts/tasks_mover.py --movetasks
```


## Dependency and Requirements

NOTE: Script created with Python 3, so run it on Python 3 only

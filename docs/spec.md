i want to create a web app called promptly to help you design, plan, and build projects with ai. it will be a web app built in react with a python api server. the app has 3 main tabs: Design, Plan, and Build.

In Design you can view and edit the project spec, tasks, and other docs:
- you can create new files with a plus button that allows you to create general supplemental project docs or task specs.
- when you click to create a new doc it asks you to prompt for what you want, you never actually write files yourself. the prompt is sent to ai to write the doc.
- if there are no files in the project yet, you are asked to write a main project spec which will describe the purpose of the project.
- there is a left side bar where you can see all project docs and open them in the main view in the middle.
- you can read the open doc and highlight text to leave a comment or ask ai a question.
- there is a button to send the doc with the comments to be addressed by ai.
- comments are stored at the end of the md files in json format in a comment `<!-- ... -->`
- the main project spec is saved in a `project.md` file at the root, additional docs are saved under a `docs/` dir, and tasks are saved under a `tasks/` dir.
- each file has metadata stored about it in a `.json` file stored in their respective doc: tasks have `tasks/tasks.json` and docs have `docs/docs.json`.
- this metadata will contain key value pairs of 1. the name of the task/doc, 2. the type of doc it is (task, project spec, doc), 3. description, 4. status (pending, in progress, in review, blocked, done, removed), 5. task group (custom field to group tasks), 6. related PRs (optional), 7. tasks/docs that this doc depends on, 8. other custom values (ex. jira tickets, assignee, etc. these aren't set by us), and 9. execution id.
- have a section in the side bar at the top showing the metadata values and allows you to add new custom values or edit them.

In Plan you can view a graph of the tasks:
- a canvas that can be zoomed in and out of and use the mouse to drag around and view it
- renders the tasks with lines connecting them based on their dependance of each other.
- tasks are colored based on their status, and "removed" tasks are never rendered by default
- hovering over a task highlights it and its entire dependency tree (all tasks that it depends on or that depend on it). tasks that it depends on have their lines highlighted in a darker color than tasks that depend on it.
- tasks are enclosed by containers with the name of the task group they belong to, so that all tasks in the same group are together. tasks can have dependency lines across groups.
- clicking on a task opens a side bar on the right, showing all of its metadata and allowing you to edit it. You can also see a list of tasks that come before it and others that come after.
- in the side bar there is also a button to open the task in the Design view (open its respective task doc), and a button to Execute on the task, which would take you to the Build tab.
- there is a toggle button at the center bottom of the page which lets you toggle between Graph view (default) and Board view.
- Board view shows tasks in a Kanban board style, with columns for each task status (so a column for tasks that are pending, in progress, blocked, in review, or done).
- You can drag tasks across columns to change their status, and can click on them for the same metadata side bar to show.
- In either view there is also a hover button somewhere to add a new tasks, which again asks you what you want the task to be and prompts the AI to create it. we can also select a task it should depend on.

in Build you can execute on tasks and have AI work on them and see its progress:
- a side bar on the left shows the tasks currently being worked on. it is separated into collapsable sections: in progress + in review tasks are at the top and open by default, blocked tasks are next and collapsed by default, then pending collapsed by default, and lastly done collapsed by default.
- when a task is selected on the side bar, it shows up in the main view showing metadata and allowing you to
	1. for pending tasks, begin execution. this will send the task to AI and set the status to in-progress.
	2. for in-progress tasks, shows steps AI has taken to build out the task, and if the AI has clarifying questions for the user, allow the user to answer them. these steps/task progress is tracked in `executions/<execution-id>/progress.json`. once the AI is done completing the task, its status is set to in-review.
	3. for in-review tasks, send feedback to AI on what else it should do and set the task back to in-progress, or create a PR, or go back to in-progress to review comments from a PR.
- there is a toggle to switch between this Info view we've been talking about and a Diff view.
- Diff view allows you to browse the files that have been changed and view their git diff side by side.
- In Diff view you can also leave comments on the changes, which are saved to `executions/<execution-id>/comments.json`. these should be partitioned by commit id so we don't lose comments after new changes are made.
- when an execution on a task is started, its id should be set in the task's metadata and vice-versa.


additonal details:
- all calls to AI will be performed by calling the claude cli in headless mode.
- when a new project is created we ask for a name and root dir for the project. this root should ideally be a codebase the project will be working on. the project docs will be saved to `<root>/projects/<project-name>/`, (ex. `<root>/projects/<project-name>/tasks/tasks.json`).

	
some more details on how AI should execute on tasks:
- a new git worktree should be created under `executions/<execution-id>/worktree/` for each execution. this should be added to the root's `.gitignore` if it isn't already.
- `progress.json` should have an array of pending questions, an array of steps taken, and a session id to keep track of the claude session for each task.
- the AI should plan out the steps that it needs to take for the task and update task-progress.json (or ideally call an api that will update it so AI doesn't accidentally mess up the file or change other tasks).
- the Ai will then continue to update the progress as it finishes those steps.
import os

from zasper_backend.models.projectModel import ProjectModel


class ProjectsManager:
    def __init__(self):
        pass

    async def get(self, path):
        projects = []
        projects_arr = ["project1", "project2"]
        for project in projects_arr:
            content = ProjectModel(
                id=project,
                name=project,
                description="string",
                total=0,
                running=0,
                completed=0,
            )
            projects.append(content)
        return projects

    async def get_single(self, path):
        projects = []
        projects_arr = ["project1", "project2"]
        for project in projects_arr:
            content = ProjectModel(
                id="string",
                name="string",
                description="string",
                total=0,
                running=0,
                completed=0,
            )
            projects.append(content)
        return projects

    def create_project(self, path):
        path = os.getcwd() + "/" + path
        with open(path, "a"):
            os.utime(path, None)

    def save(self, model, path):
        pass

    def delete_project(self, path):
        pass

    def rename_project(self, path):
        pass

import os
from flask import Config
from morocco.util import get_logger


def load_config_models():
    # pylint: disable=too-few-public-methods, invalid-name

    from sqlalchemy import Column, Integer, String, ForeignKey
    from sqlalchemy.orm import relationship
    from sqlalchemy.ext.declarative import declarative_base

    model_base_class = declarative_base()

    class Project(model_base_class):
        __tablename__ = 'db_project'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        settings = relationship('ProjectSetting', back_populates='project')

        def __repr__(self):
            return '<Project(name={})>'.format(self.name)

    class ProjectSetting(model_base_class):
        __tablename__ = 'db_projectsetting'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        value = Column(String)
        project_id = Column(Integer, ForeignKey('db_project.id'))
        project = relationship(Project, back_populates='settings')

        def __repr__(self):
            return '<ProjectSetting(name={},value={})>'.format(self.name, self.value)

    return Project, ProjectSetting


def load_config(app_config: Config) -> None:
    logger = get_logger(__name__)
    try:
        db_uri = os.environ['MOROCCO_DATABASE_URI']
        project_name = os.environ['MOROCCO_CURRENT_PROJECT']

        app_config['is_local_server'] = os.environ.get('MOROCCO_LOCAL_SERVER') == 'True'
        app_config['SQLALCHEMY_DATABASE_URI'] = db_uri
        app_config['MOROCCO_CURRENT_PROJECT'] = project_name
        app_config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    except KeyError:
        raise EnvironmentError('Missing environment MOROCCO_DATABASE_URI and/or MOROCCO_CURRENT_PROJECT.')

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_uri)
    session_class = sessionmaker()
    session_class.configure(bind=engine)
    session = session_class()

    project_model_class, _ = load_config_models()

    project = session.query(project_model_class).filter(project_model_class.name == project_name).one()
    for setting in project.settings:
        logger.info('add setting {}'.format(setting.name))
        app_config[setting.name] = setting.value

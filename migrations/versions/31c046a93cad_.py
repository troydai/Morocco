"""empty message

Revision ID: 31c046a93cad
Revises: e6718ab0dca8
Create Date: 2017-08-10 10:48:20.134951

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '31c046a93cad'
down_revision = 'e6718ab0dca8'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('db_access_key', sa.Column('name', sa.String(), nullable=False))
    op.drop_column('db_access_key', 'id')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('db_access_key', sa.Column('id', sa.INTEGER(), nullable=False))
    op.drop_column('db_access_key', 'name')
    # ### end Alembic commands ###

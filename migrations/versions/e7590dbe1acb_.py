"""empty message

Revision ID: e7590dbe1acb
Revises: 31c046a93cad
Create Date: 2017-08-10 15:29:55.425557

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7590dbe1acb'
down_revision = '31c046a93cad'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('db_webhook_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(), nullable=True),
    sa.Column('content', sa.String(), nullable=True),
    sa.Column('signature', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('db_webhook_event')
    # ### end Alembic commands ###

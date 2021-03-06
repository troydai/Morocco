"""empty message

Revision ID: 7007b8960739
Revises: 6966cba43f6e
Create Date: 2017-08-16 22:31:50.125633

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7007b8960739'
down_revision = '6966cba43f6e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('db_test_run', 'failed_tests')
    op.drop_column('db_test_run', 'total_tests')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('db_test_run', sa.Column('total_tests', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('db_test_run', sa.Column('failed_tests', sa.INTEGER(), autoincrement=False, nullable=True))
    # ### end Alembic commands ###

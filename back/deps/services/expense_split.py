from typing import Annotated, TypeAlias
from fastapi import Depends

from back.services.expense_split import ExpenseSplitService


def get_expense_split_service() -> ExpenseSplitService:
    return ExpenseSplitService()


ExpenseSplitServiceDep: TypeAlias = Annotated[ExpenseSplitService, Depends(get_expense_split_service)]

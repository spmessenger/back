from __future__ import annotations

from dataclasses import dataclass
import time
from uuid import uuid4


@dataclass
class ExpenseSplit:
    id: str
    chat_id: int
    title: str
    amount_minor: int
    currency: str
    payer_user_id: int
    created_by_user_id: int
    shares_minor_by_user_id: dict[int, int]
    created_at: float


@dataclass
class ExpenseSettlement:
    from_user_id: int
    to_user_id: int
    amount_minor: int


@dataclass
class ExpensePayment:
    id: str
    chat_id: int
    from_user_id: int
    to_user_id: int
    amount_minor: int
    created_by_user_id: int
    created_at: float


class ExpenseSplitService:
    _expenses_by_chat: dict[int, list[ExpenseSplit]] = {}
    _expenses_by_id: dict[str, ExpenseSplit] = {}
    _payments_by_chat: dict[int, list[ExpensePayment]] = {}

    def list_expenses(self, *, chat_id: int) -> list[ExpenseSplit]:
        return list(self._expenses_by_chat.get(chat_id, []))

    def list_payments(self, *, chat_id: int) -> list[ExpensePayment]:
        return list(self._payments_by_chat.get(chat_id, []))

    def create_expense(
        self,
        *,
        chat_id: int,
        title: str,
        amount_minor: int,
        currency: str,
        payer_user_id: int,
        created_by_user_id: int,
        participant_user_ids: list[int],
        shares_minor_by_user_id: dict[int, int] | None = None,
    ) -> ExpenseSplit:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError('Expense title is required')
        if amount_minor <= 0:
            raise ValueError('Amount must be greater than 0')
        if len(participant_user_ids) == 0:
            raise ValueError('At least one participant is required')

        unique_participants = sorted(set(participant_user_ids))
        if payer_user_id not in unique_participants:
            raise ValueError('Payer must be included in participants')

        if shares_minor_by_user_id is None:
            shares_minor_by_user_id = self._build_equal_shares(
                amount_minor=amount_minor,
                participant_user_ids=unique_participants,
                payer_user_id=payer_user_id,
            )
        else:
            shares_minor_by_user_id = {
                int(user_id): int(share)
                for user_id, share in shares_minor_by_user_id.items()
            }
            if set(shares_minor_by_user_id.keys()) != set(unique_participants):
                raise ValueError('Custom shares must include exactly all selected participants')
            if any(share < 0 for share in shares_minor_by_user_id.values()):
                raise ValueError('Share amount cannot be negative')
            if sum(shares_minor_by_user_id.values()) != amount_minor:
                raise ValueError('Custom shares must sum to total amount')

        expense = ExpenseSplit(
            id=uuid4().hex,
            chat_id=chat_id,
            title=normalized_title,
            amount_minor=amount_minor,
            currency=currency.upper().strip() or 'RUB',
            payer_user_id=payer_user_id,
            created_by_user_id=created_by_user_id,
            shares_minor_by_user_id=shares_minor_by_user_id,
            created_at=time.time(),
        )
        chat_expenses = self._expenses_by_chat.setdefault(chat_id, [])
        chat_expenses.append(expense)
        self._expenses_by_id[expense.id] = expense
        return expense

    def compute_balances(self, *, chat_id: int) -> dict[int, int]:
        balances: dict[int, int] = {}
        for expense in self._expenses_by_chat.get(chat_id, []):
            balances[expense.payer_user_id] = balances.get(expense.payer_user_id, 0) + expense.amount_minor
            for user_id, share_minor in expense.shares_minor_by_user_id.items():
                balances[user_id] = balances.get(user_id, 0) - share_minor
        return balances

    def compute_settlements(self, *, chat_id: int) -> list[ExpenseSettlement]:
        balances = self.compute_balances(chat_id=chat_id)
        return self._compute_settlements_from_balances(balances=balances)

    def compute_outstanding_settlements(self, *, chat_id: int) -> list[ExpenseSettlement]:
        raw_settlements = self.compute_settlements(chat_id=chat_id)
        paid_by_pair: dict[tuple[int, int], int] = {}
        for payment in self._payments_by_chat.get(chat_id, []):
            pair_key = (payment.from_user_id, payment.to_user_id)
            paid_by_pair[pair_key] = paid_by_pair.get(pair_key, 0) + payment.amount_minor

        outstanding: list[ExpenseSettlement] = []
        for settlement in raw_settlements:
            pair_key = (settlement.from_user_id, settlement.to_user_id)
            paid_amount = paid_by_pair.get(pair_key, 0)
            remaining_amount = max(0, settlement.amount_minor - paid_amount)
            if remaining_amount > 0:
                outstanding.append(
                    ExpenseSettlement(
                        from_user_id=settlement.from_user_id,
                        to_user_id=settlement.to_user_id,
                        amount_minor=remaining_amount,
                    )
                )
        return outstanding

    def mark_settlement_paid(
        self,
        *,
        chat_id: int,
        from_user_id: int,
        to_user_id: int,
        amount_minor: int,
        created_by_user_id: int,
    ) -> ExpensePayment:
        if amount_minor <= 0:
            raise ValueError('Payment amount must be greater than 0')

        outstanding_by_pair = {
            (settlement.from_user_id, settlement.to_user_id): settlement.amount_minor
            for settlement in self.compute_outstanding_settlements(chat_id=chat_id)
        }
        pair_key = (from_user_id, to_user_id)
        max_payable = outstanding_by_pair.get(pair_key, 0)
        if max_payable <= 0:
            raise ValueError('No outstanding settlement for selected users')
        if amount_minor > max_payable:
            raise ValueError('Payment amount is greater than outstanding debt')

        payment = ExpensePayment(
            id=uuid4().hex,
            chat_id=chat_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount_minor=amount_minor,
            created_by_user_id=created_by_user_id,
            created_at=time.time(),
        )
        chat_payments = self._payments_by_chat.setdefault(chat_id, [])
        chat_payments.append(payment)
        return payment

    @staticmethod
    def _compute_settlements_from_balances(*, balances: dict[int, int]) -> list[ExpenseSettlement]:
        creditors: list[list[int]] = []
        debtors: list[list[int]] = []
        for user_id, balance_minor in balances.items():
            if balance_minor > 0:
                creditors.append([user_id, balance_minor])
            elif balance_minor < 0:
                debtors.append([user_id, -balance_minor])

        creditors.sort(key=lambda item: item[1], reverse=True)
        debtors.sort(key=lambda item: item[1], reverse=True)

        settlements: list[ExpenseSettlement] = []
        creditor_idx = 0
        debtor_idx = 0
        while creditor_idx < len(creditors) and debtor_idx < len(debtors):
            creditor_user_id, creditor_left = creditors[creditor_idx]
            debtor_user_id, debtor_left = debtors[debtor_idx]
            transfer = min(creditor_left, debtor_left)
            if transfer > 0:
                settlements.append(
                    ExpenseSettlement(
                        from_user_id=debtor_user_id,
                        to_user_id=creditor_user_id,
                        amount_minor=transfer,
                    )
                )
            creditors[creditor_idx][1] -= transfer
            debtors[debtor_idx][1] -= transfer
            if creditors[creditor_idx][1] == 0:
                creditor_idx += 1
            if debtors[debtor_idx][1] == 0:
                debtor_idx += 1
        return settlements

    def total_expenses_minor(self, *, chat_id: int) -> int:
        return sum(expense.amount_minor for expense in self._expenses_by_chat.get(chat_id, []))

    @staticmethod
    def _build_equal_shares(
        *,
        amount_minor: int,
        participant_user_ids: list[int],
        payer_user_id: int,
    ) -> dict[int, int]:
        participant_count = len(participant_user_ids)
        if participant_count == 0:
            raise ValueError('At least one participant is required')
        base_share = amount_minor // participant_count
        remainder = amount_minor % participant_count
        shares = {user_id: base_share for user_id in participant_user_ids}
        if remainder > 0:
            shares[payer_user_id] += remainder
        return shares

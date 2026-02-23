from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    add_user = State()
    remove_user = State()
    assign_user_profiles = State()
    add_panel = State()
    test_panel = State()
    create_profile = State()
    toggle_profile = State()
    capacity_report = State()


class UserStates(StatesGroup):
    choose_profile = State()
    choose_quantity = State()

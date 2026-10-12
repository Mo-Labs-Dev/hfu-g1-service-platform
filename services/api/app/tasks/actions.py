from enum import Enum


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    DETECT_OBJECT = "detect_object"
    PICK = "pick"
    PLACE = "place"
    MANIPULATE = "manipulate"
    CLEAN = "clean"
    SPEAK = "speak"
    WAIT = "wait"
    VERIFY = "verify"
    RETURN_HOME = "return_home"
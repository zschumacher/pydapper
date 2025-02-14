import typing as t


SingleParamType = tuple | dict | object
ListParamType = list[tuple] | list[dict]
ParamType = SingleParamType | ListParamType


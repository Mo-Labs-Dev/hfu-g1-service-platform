
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.models.task import (
    RobotTask,
    StepStatus,
    TaskStatus,
    TaskStep,
)
from app.robot.base import BaseRobot
from app.tasks.actions import ActionType


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class TaskBusyError(Exception):
    pass


class TaskEngine:
    def __init__(
        self,
        robot: BaseRobot,
        event_handler: EventHandler | None = None,
    ):
        self.robot = robot
        self.event_handler = event_handler
        self.current_task: RobotTask | None = None
        self.cancel_requested = False
        self._busy = False
        self._background_tasks: set[asyncio.Task] = set()

    @property
    def is_busy(self) -> bool:
        return self._busy

    async def _emit(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        if self.event_handler is None:
            return

        try:
            await self.event_handler(
                {
                    "type": event_type,
                    "data": data,
                }
            )
        except Exception as error:
            print(f"[TASK EVENT ERROR] {error}")

    def start(self, task: RobotTask) -> RobotTask:
        """
        Reserve the engine synchronously before scheduling execution.
        This prevents overlapping requests on the same engine.
        """
        if self._busy:
            raise TaskBusyError(
                "Another robot task is already running."
            )

        if not task.steps:
            raise ValueError(
                "Cannot execute a workflow without steps."
            )

        self._busy = True
        self.cancel_requested = False
        self.current_task = task
        task.status = TaskStatus.PENDING

        try:
            background = asyncio.create_task(
                self.execute(task)
            )
        except Exception:
            self._busy = False
            self.current_task = None
            raise

        self._background_tasks.add(background)
        background.add_done_callback(
            self._background_tasks.discard
        )

        return task

    async def execute(self, task: RobotTask) -> RobotTask:
        if self._busy and self.current_task is not task:
            raise TaskBusyError(
                "Another robot task is already running."
            )

        if not task.steps:
            raise ValueError(
                "Cannot execute a workflow without steps."
            )

        if not self._busy:
            self._busy = True
            self.current_task = task
            self.cancel_requested = False

        task.status = TaskStatus.RUNNING

        try:
            print(f"\n[TASK] Starting: {task.name}")

            await self._emit(
                "task_started",
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "status": task.status.value,
                    "total_steps": len(task.steps),
                },
            )

            for index, step in enumerate(task.steps):
                if self.cancel_requested:
                    task.status = TaskStatus.CANCELLED

                    await self._emit(
                        "task_cancelled",
                        {
                            "task_id": task.id,
                            "status": task.status.value,
                        },
                    )
                    return task

                task.current_step = index
                step.status = StepStatus.RUNNING

                print(
                    f"[STEP {index + 1}/{len(task.steps)}] "
                    f"{step.name}"
                )

                await self._emit(
                    "step_started",
                    {
                        "task_id": task.id,
                        "step_id": step.id,
                        "step_name": step.name,
                        "step_index": index,
                        "action": step.action.value,
                        "status": step.status.value,
                    },
                )

                try:
                    success = await self._execute_step(step)

                    if not success:
                        step.status = StepStatus.FAILED
                        task.status = TaskStatus.FAILED

                        await self._emit(
                            "step_failed",
                            {
                                "task_id": task.id,
                                "step_id": step.id,
                                "step_index": index,
                                "status": step.status.value,
                            },
                        )

                        await self._emit(
                            "task_failed",
                            {
                                "task_id": task.id,
                                "status": task.status.value,
                            },
                        )
                        return task

                    step.status = StepStatus.COMPLETED

                    print(f"[STEP] Completed: {step.name}")

                    await self._emit(
                        "step_completed",
                        {
                            "task_id": task.id,
                            "step_id": step.id,
                            "step_name": step.name,
                            "step_index": index,
                            "action": step.action.value,
                            "status": step.status.value,
                        },
                    )

                except asyncio.CancelledError:
                    raise

                except Exception as error:
                    step.status = StepStatus.FAILED
                    task.status = TaskStatus.FAILED

                    print(
                        f"[TASK ERROR] {step.name}: {error}"
                    )

                    await self._emit(
                        "task_failed",
                        {
                            "task_id": task.id,
                            "step_id": step.id,
                            "step_index": index,
                            "status": task.status.value,
                            "error": str(error),
                        },
                    )
                    return task

            task.status = TaskStatus.COMPLETED

            print(f"[TASK] Completed: {task.name}")

            await self._emit(
                "task_completed",
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "status": task.status.value,
                },
            )

            return task

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED

            await self._emit(
                "task_cancelled",
                {
                    "task_id": task.id,
                    "status": task.status.value,
                },
            )
            raise

        except Exception as error:
            task.status = TaskStatus.FAILED

            await self._emit(
                "task_failed",
                {
                    "task_id": task.id,
                    "status": task.status.value,
                    "error": str(error),
                },
            )
            return task

        finally:
            self._busy = False

    async def _execute_step(self, step: TaskStep) -> bool:
        action = step.action
        params = step.parameters

        await self._emit(
            "robot_action",
            {
                "task_id": (
                    self.current_task.id
                    if self.current_task is not None
                    else None
                ),
                "action": action.value,
                "parameters": params,
            },
        )

        if action == ActionType.NAVIGATE:
            return await self.robot.navigate(
                params["location_id"]
            )

        if action == ActionType.DETECT_OBJECT:
            return await self.robot.detect_object(
                params["object_name"]
            )

        if action == ActionType.PICK:
            return await self.robot.pick(
                params["object_name"]
            )

        if action == ActionType.PLACE:
            return await self.robot.place(
                params["target"]
            )

        if action == ActionType.MANIPULATE:
            return await self.robot.manipulate(
                params["target"],
                params["operation"],
            )

        if action == ActionType.CLEAN:
            return await self.robot.clean(
                params["target"]
            )

        if action == ActionType.SPEAK:
            return await self.robot.speak(
                params["text"]
            )

        if action == ActionType.VERIFY:
            return await self.robot.verify(
                params["target"],
                params["condition"],
            )

        if action == ActionType.WAIT:
            seconds = params.get("seconds", 1)

            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, (int, float))
                or not 0 <= seconds <= 300
            ):
                raise ValueError(
                    "WAIT seconds must be between 0 and 300."
                )

            await asyncio.sleep(seconds)
            return True

        if action == ActionType.RETURN_HOME:
            return await self.robot.return_home()

        raise ValueError(
            f"Unsupported action: {action}"
        )

    async def cancel(self) -> None:
        self.cancel_requested = True
        await self.robot.stop()

    def get_current_task(self) -> RobotTask | None:
        return self.current_task

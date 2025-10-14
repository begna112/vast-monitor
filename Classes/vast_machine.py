from pydantic import BaseModel
from typing import Optional, List, Union, Dict, Any


class MachineMaintenance(BaseModel):
    duration_hours: Optional[float]
    id: int
    machine_id: int
    maintenance_category: Optional[str]
    maintenance_reason: Optional[str]
    start_time: Optional[float]


class VastMachine(BaseModel):
    clients: List[Dict[str, Any]]
    id: int
    machine_id: int
    hostname: str
    geolocation: str
    timeout: int
    mobo_name: str
    num_gpus: int
    total_flops: float
    gpu_name: str
    gpu_ram: int
    gpu_max_cur_temp: float
    gpu_lanes: int
    gpu_mem_bw: float
    bw_nvlink: Optional[float]
    pcie_bw: float
    pci_gen: float
    cpu_name: str
    cpu_ram: int
    cpu_cores: int
    cpu_arch: str
    listed: bool
    start_date: Optional[float] = None
    end_date: Optional[float] = None
    duration: Optional[float]
    credit_discount_max: Optional[float]
    listed_min_gpu_count: Optional[int]
    listed_gpu_cost: Optional[float]
    listed_storage_cost: Optional[float]
    listed_volume_cost: Optional[float]
    listed_inet_up_cost: Optional[float]
    listed_inet_down_cost: Optional[float]
    min_bid_price: float
    gpu_occupancy: str
    bid_gpu_cost: Optional[float]
    bid_image: Optional[str]
    bid_image_args: Optional[List[Any]]
    bid_image_args_str: Optional[str]
    disk_space: float
    max_disk_space: int
    alloc_disk_space: Optional[int]
    avail_disk_space: int
    disk_name: str
    disk_bw: float
    inet_up: float
    inet_down: float
    earn_hour: float
    earn_day: float
    verification: str
    error_description: Optional[str]
    current_rentals_running: int
    current_rentals_running_on_demand: int
    current_rentals_resident: int
    current_rentals_on_demand: int
    reliability2: float
    direct_port_count: int
    public_ipaddr: str
    num_reports: Optional[int]
    num_recent_reports: Optional[float]
    client_end_date: Optional[float]
    machine_maintenance: Optional[Union[str, List[MachineMaintenance]]]
    driver_version: str
    cuda_max_good: float
    kernel_version: Optional[str]
    ubuntu_version: str

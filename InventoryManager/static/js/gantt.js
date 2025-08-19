/**
 * 甘特图JavaScript逻辑
 */

class GanttChart {
    constructor() {
        this.currentDate = new Date();
        this.startDate = new Date();
        this.endDate = new Date();
        this.devices = [];
        this.rentals = [];
        this.availableSlot = null;
        
        // 日历相关
        this.calendarDate = new Date();
        this.selectedStartDate = null;
        this.selectedEndDate = null;
        this.isSelectingEnd = false;
        
        this.init();
    }
    
    init() {
        this.setupDateRange();
        this.loadData();
        this.setupEventListeners();
        this.initRegionSelectors();
        this.updateStats();
    }
    
    setupDateRange() {
        // 设置默认显示当前月
        const today = new Date();
        this.startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        this.endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.currentDate = today;
        
        this.updateDateNavigation();
    }
    
    setupEventListeners() {
        // 设置日期输入框的默认值
        document.getElementById('query-start-date').value = this.formatDate(this.startDate);
        document.getElementById('query-end-date').value = this.formatDate(this.endDate);
    }
    
    async loadData() {
        try {
            const response = await axios.get('/api/gantt/data', {
                params: {
                    start_date: this.formatDate(this.startDate),
                    end_date: this.formatDate(this.endDate)
                }
            });
            
            if (response.data.success) {
                this.devices = response.data.data.devices;
                this.rentals = response.data.data.rentals;
                this.renderGantt();
                this.updateStats();
                this.populateFilters();
            } else {
                console.error('加载数据失败:', response.data.error);
            }
        } catch (error) {
            this.showToast('加载数据异常: ' + this.getErrorMessage(error), 'error');
            console.error('加载数据异常:', error);
        }
    }
    
    renderGantt() {
        const container = document.getElementById('gantt-chart');
        container.innerHTML = '';
        
        // 创建甘特图
        this.createHeader(container);
        this.createRows(container);
    }
    
    createHeader(container) {
        const header = document.createElement('div');
        header.className = 'gantt-header';
        
        const headerRow = document.createElement('div');
        headerRow.className = 'gantt-row';
        
        // 设备列标题
        const deviceHeader = document.createElement('div');
        deviceHeader.className = 'gantt-cell gantt-device-cell';
        deviceHeader.innerHTML = '<strong>设备</strong>';
        headerRow.appendChild(deviceHeader);
        
        // 日期列标题
        const currentDate = new Date(this.startDate);
        while (currentDate <= this.endDate) {
            const dateHeader = document.createElement('div');
            dateHeader.className = 'gantt-cell gantt-date-cell';
            
            // 检查是否是今天
            if (this.isToday(currentDate)) {
                dateHeader.className += ' gantt-today';
            }
            
            dateHeader.innerHTML = `
                <div>${this.formatDateHeader(currentDate)}</div>
            `;
            headerRow.appendChild(dateHeader);
            
            currentDate.setDate(currentDate.getDate() + 1);
        }
        
        header.appendChild(headerRow);
        container.appendChild(header);
    }
    
    createRows(container) {
        this.devices.forEach(device => {
            const row = document.createElement('div');
            row.className = 'gantt-row';
            
            // 设备信息列
            const deviceCell = document.createElement('div');
            deviceCell.className = 'gantt-cell gantt-device-cell';
            deviceCell.innerHTML = `
                <div>
                    <div><strong>${device.name}</strong></div>
                    <div style="font-size: 0.7em; color: #6c757d;">
                        编号: ${device.serial_number || 'N/A'}
                    </div>
                    <div style="font-size: 0.7em; color: #6c757d;">
                        位置: ${device.location || 'N/A'} | 状态: ${this.getStatusText(device.status)}
                    </div>
                </div>
            `;
            row.appendChild(deviceCell);
            
            // 日期列
            const currentDate = new Date(this.startDate);
            while (currentDate <= this.endDate) {
                const dateCell = document.createElement('div');
                dateCell.className = 'gantt-cell';
                
                // 检查是否有租赁记录（扩展到寄出-收回时间）
                const rental = this.getRentalForDeviceAndDate(device.id, currentDate);
                if (rental) {
                    const el = this.createOccupancyElement(rental, currentDate);
                    if (el) dateCell.appendChild(el);
                } else if (device.status === 'available') {
                    dateCell.className += ' available';
                }
                
                row.appendChild(dateCell);
                currentDate.setDate(currentDate.getDate() + 1);
            }
            
            container.appendChild(row);
        });
    }
    
    // 计算寄出/收回时间（优先使用后端提供字段）
    getShipOutDate(rental) {
        if (rental.ship_out_time) {
            return new Date(rental.ship_out_time);
        }
        const startDate = new Date(rental.start_date);
        const logisticsDays = 1; // 兜底：老数据没有物流天数则按1天
        const shipOut = new Date(startDate);
        shipOut.setDate(shipOut.getDate() - 1 - logisticsDays);
        return shipOut;
    }
    
    getShipInDate(rental) {
        if (rental.ship_in_time) {
            return new Date(rental.ship_in_time);
        }
        const endDate = new Date(rental.end_date);
        const logisticsDays = 1;
        const shipIn = new Date(endDate);
        shipIn.setDate(shipIn.getDate() + 1 + logisticsDays);
        return shipIn;
    }
    
    // 在单元格内渲染占用条（外层：寄出-收回；内层：租赁期间）
    createOccupancyElement(rental, currentDate) {
        const dayStr = this.formatDate(currentDate);
        const shipOut = this.getShipOutDate(rental);
        const shipIn = this.getShipInDate(rental);
        const startDate = new Date(rental.start_date);
        const endDate = new Date(rental.end_date);
        
        const inFullRange = this.formatDate(shipOut) <= dayStr && dayStr <= this.formatDate(shipIn);
        if (!inFullRange) return null;
        
        const inRentalRange = this.formatDate(startDate) <= dayStr && dayStr <= this.formatDate(endDate);
        
        const wrap = document.createElement('div');
        wrap.className = 'gantt-occupy';
        
        if (inRentalRange) {
            const inner = document.createElement('div');
            inner.className = 'gantt-occupy-inner';
            
            // 在租赁时间段显示客户姓名
            inner.textContent = rental.customer_name;
            
            // 在租赁时间段添加编辑按钮
            const editBtn = document.createElement('button');
            editBtn.className = 'edit-btn';
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.title = '编辑租赁记录';
            editBtn.onclick = (e) => {
                e.stopPropagation();
                this.editRental(rental);
            };
            inner.appendChild(editBtn);
            
            // 在租赁时间段添加删除按钮
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'delete-btn';
            deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
            deleteBtn.title = '删除租赁记录';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                this.deleteRental(rental.id);
            };
            inner.appendChild(deleteBtn);
            
            wrap.appendChild(inner);
        }
        
        // 添加悬停提示信息
        wrap.appendChild(this.createRentalInfoElement(rental, shipOut, shipIn));
        
        return wrap;
    }
    
    createCompleteRentalElements(rental, currentDate) {
        const elements = [];
        const currentDateStr = this.formatDate(currentDate);
        
        // 确保日期是Date对象
        const startDate = new Date(rental.start_date);
        const endDate = new Date(rental.end_date);
        
        // 计算寄出时间和收回时间
        const logisticsDays = 1; // 默认物流时间1天，可以根据实际情况调整
        const shipOutDate = new Date(startDate);
        shipOutDate.setDate(shipOutDate.getDate() - 1 - logisticsDays);
        
        const shipInDate = new Date(endDate);
        shipInDate.setDate(shipInDate.getDate() + 1 + logisticsDays);
        
        // 检查当前日期是否在寄出到收回的时间范围内
        if (currentDateStr >= this.formatDate(shipOutDate) && currentDateStr <= this.formatDate(shipInDate)) {
            const rentalElement = document.createElement('div');
            
            // 判断当前日期属于哪个时间段
            if (currentDateStr >= this.formatDate(shipOutDate) && currentDateStr < this.formatDate(startDate)) {
                // 寄出物流时间
                rentalElement.className = 'gantt-rental logistics-time';
                rentalElement.textContent = '寄出';
            } else if (currentDateStr >= this.formatDate(startDate) && currentDateStr <= this.formatDate(endDate)) {
                // 租赁时间
                rentalElement.className = 'gantt-rental rental-time';
                rentalElement.textContent = rental.customer_name;
            } else {
                // 收回物流时间
                rentalElement.className = 'gantt-rental logistics-time';
                rentalElement.textContent = '收回';
            }
            
            // 添加悬停提示信息
            rentalElement.appendChild(this.createRentalInfoElement(rental, shipOutDate, shipInDate));
            
            // 添加删除按钮（只在租赁时间显示）
            if (currentDateStr >= this.formatDate(startDate) && currentDateStr <= this.formatDate(endDate)) {
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-btn';
                deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
                deleteBtn.onclick = (e) => {
                    e.stopPropagation();
                    this.deleteRental(rental.id);
                };
                rentalElement.appendChild(deleteBtn);
            }
            
            elements.push(rentalElement);
        }
        
        return elements;
    }
    
    createRentalInfoElement(rental, shipOutDate, shipInDate) {
        const infoDiv = document.createElement('div');
        infoDiv.className = 'rental-info';
        
        const logisticsDays = 1; // 默认物流时间1天
        
        infoDiv.innerHTML = `
            <div class="info-row">
                <span class="info-label">客户名:</span>
                <span class="info-value">${rental.customer_name}</span>
            </div>
            <div class="info-row">
                <span class="info-label">联系方式:</span>
                <span class="info-value">${rental.customer_phone || 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">寄出时间:</span>
                <span class="info-value">${this.formatDate(shipOutDate)}</span>
            </div>
            <div class="info-row">
                <span class="info-label">租赁开始:</span>
                <span class="info-value">${this.formatDate(new Date(rental.start_date))}</span>
            </div>
            <div class="info-row">
                <span class="info-label">租赁结束:</span>
                <span class="info-value">${this.formatDate(new Date(rental.end_date))}</span>
            </div>
            <div class="info-row">
                <span class="info-label">收回时间:</span>
                <span class="info-value">${this.formatDate(shipInDate)}</span>
            </div>
            <div class="info-row">
                <span class="info-label">寄出运单:</span>
                <span class="info-value">${rental.ship_out_tracking_no || 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">寄回运单:</span>
                <span class="info-value">${rental.ship_in_tracking_no || 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">目的地:</span>
                <span class="info-value">${rental.destination || 'N/A'}</span>
            </div>
        `;
        
        return infoDiv;
    }
    
    async deleteRental(rentalId) {
        if (!confirm('确定要删除这个租赁记录吗？此操作不可恢复。')) {
            return;
        }
        
        try {
            const response = await axios.delete(`/web/rentals/${rentalId}`);
            
            if (response.data.success) {
                this.showToast('租赁记录删除成功', 'success');
                // 刷新甘特图数据
                this.loadData();
            } else {
                this.showToast('删除失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('删除失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    editRental(rental) {
        // 填充编辑表单
        document.getElementById('edit-rental-id').value = rental.id;
        document.getElementById('edit-start-date').value = (typeof rental.start_date === 'string') ? rental.start_date : this.formatDate(new Date(rental.start_date));
        document.getElementById('edit-end-date').value = (typeof rental.end_date === 'string') ? rental.end_date : this.formatDate(new Date(rental.end_date));
        document.getElementById('edit-customer-name').value = rental.customer_name;
        document.getElementById('edit-customer-phone').value = rental.customer_phone || '';
        document.getElementById('edit-destination').value = rental.destination || '';
        document.getElementById('edit-ship-out-tracking').value = rental.ship_out_tracking_no || '';
        document.getElementById('edit-ship-in-tracking').value = rental.ship_in_tracking_no || '';
        
        // 显示编辑模态框
        const modal = new bootstrap.Modal(document.getElementById('editRentalModal'));
        modal.show();
    }
    
    async updateRental() {
        const rentalId = document.getElementById('edit-rental-id').value;
        const formData = {
            end_date: document.getElementById('edit-end-date').value,
            customer_phone: document.getElementById('edit-customer-phone').value,
            destination: document.getElementById('edit-destination').value,
            ship_out_tracking_no: document.getElementById('edit-ship-out-tracking').value,
            ship_in_tracking_no: document.getElementById('edit-ship-in-tracking').value
        };
        
        try {
            const response = await axios.put(`/web/rentals/${rentalId}`, formData);
            
            if (response.data.success) {
                this.showToast('租赁记录更新成功', 'success');
                
                // 关闭模态框
                const modal = bootstrap.Modal.getInstance(document.getElementById('editRentalModal'));
                modal.hide();
                
                // 刷新数据
                this.loadData();
            } else {
                this.showToast('更新失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('更新失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    // 重写：在寄出-收回范围内判断有无记录
    getRentalForDeviceAndDate(deviceId, date) {
        const dateStr = this.formatDate(date);
        return this.rentals.find(rental => {
            if (rental.device_id !== deviceId) return false;
            if (rental.status === 'cancelled') return false;
            const shipOutStr = this.formatDate(this.getShipOutDate(rental));
            const shipInStr = this.formatDate(this.getShipInDate(rental));
            return shipOutStr <= dateStr && dateStr <= shipInStr;
        });
    }
    
    openBookingModal() {
        // 确保地区下拉已填充
        this.ensureRegionSelectorsPopulated();
        
        // 重置表单和状态
        document.getElementById('bookingForm').reset();
        document.getElementById('submit-booking-btn').disabled = true;
        this.availableSlot = null;
        
        // 重置日历选择
        this.resetCalendarSelection();
        
        // 设置默认物流时间
        document.getElementById('logistics-days').value = '1';
        
        // 显示模态框
        const modal = new bootstrap.Modal(document.getElementById('bookingModal'));
        modal.show();
        
        // 模态框显示后渲染日历
        setTimeout(() => {
            this.renderCalendar();
        }, 100);
    }
    
    async findAvailableSlot() {
        if (!this.selectedStartDate || !this.selectedEndDate) {
            this.showToast('请先在日历中选择租赁开始和结束日期', 'error');
            return;
        }
        
        const logisticsDays = parseInt(document.getElementById('logistics-days').value);
        
        if (!logisticsDays || logisticsDays < -1) {
            this.showToast('物流时间不能少于-1天', 'error');
            return;
        }
        
        // 验证日期 - 允许开始和结束日期是同一天
        if (this.selectedStartDate > this.selectedEndDate) {
            this.showToast('开始日期不能晚于结束日期', 'error');
            return;
        }
        
        try {
            // 调用后端API查找档期
            const response = await axios.post('/api/rentals/find-slot', {
                start_date: this.formatDate(this.selectedStartDate),
                end_date: this.formatDate(this.selectedEndDate),
                logistics_days: logisticsDays
            });
            
            if (response.data.success) {
                const data = response.data.data;
                this.availableSlot = {
                    device: data.device,
                    shipOutDate: new Date(data.ship_out_date),
                    shipInDate: new Date(data.ship_in_date)
                };
                
                document.getElementById('submit-booking-btn').disabled = false;
                this.showToast(data.message, 'success');
            } else {
                this.showToast(response.data.error, 'error');
                document.getElementById('submit-booking-btn').disabled = true;
            }
        } catch (error) {
            if (error.response && error.response.status === 404) {
                this.showToast('未找到可用档期，请调整时间或物流时间', 'error');
            } else {
                this.showToast('查找档期失败: ' + this.getErrorMessage(error), 'error');
            }
            document.getElementById('submit-booking-btn').disabled = true;
        }
    }
    
    async submitBooking() {
        if (!this.selectedStartDate || !this.selectedEndDate) {
            this.showToast('请先选择租赁开始和结束日期', 'error');
            return;
        }
        
        const formData = {
            device_id: this.availableSlot.device.id,
            start_date: this.formatDate(this.selectedStartDate),
            end_date: this.formatDate(this.selectedEndDate),
            customer_name: document.getElementById('customer-name').value,
            customer_phone: document.getElementById('customer-phone').value,
            destination: this.getDestinationString(),
            ship_out_time: this.formatDate(this.availableSlot.shipOutDate),
            ship_in_time: this.formatDate(this.availableSlot.shipInDate)
        };
        
        try {
            const response = await axios.post('/api/rentals', formData);
            
            if (response.data.success) {
                this.showToast('预定成功！', 'success');
                
                // 关闭模态框
                const modal = bootstrap.Modal.getInstance(document.getElementById('bookingModal'));
                modal.hide();
                
                // 刷新数据
                this.loadData();
                
                // 清空表单和日历选择
                document.getElementById('bookingForm').reset();
                document.getElementById('submit-booking-btn').disabled = true;
                this.availableSlot = null;
                this.resetCalendarSelection();
            } else {
                this.showToast('创建失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('创建失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    getDestinationString() {
        const province = document.getElementById('province-select').value;
        const city = document.getElementById('city-select').value;
        const district = document.getElementById('district-select').value;
        return `${province} ${city} ${district}`.trim();
    }
    
    async queryInventory() {
        const startDate = document.getElementById('query-start-date').value;
        const endDate = document.getElementById('query-end-date').value;
        const deviceType = document.getElementById('query-device-type').value;
        
        if (!startDate || !endDate) {
            this.showToast('请选择开始和结束日期', 'error');
            return;
        }
        
        try {
            const response = await axios.get('/api/inventory/available', {
                params: {
                    start_date: startDate,
                    end_date: endDate,
                    device_type: deviceType
                }
            });
            
            if (response.data.success) {
                this.displayQueryResults(response.data.data);
            } else {
                this.showToast('查询失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('查询失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    displayQueryResults(devices) {
        const resultsDiv = document.getElementById('query-results');
        
        if (devices.length === 0) {
            resultsDiv.innerHTML = '<div class="alert alert-info">在指定时间段内没有可用设备</div>';
            return;
        }
        
        let html = `
            <div class="alert alert-success">
                找到 ${devices.length} 台可用设备
            </div>
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>设备名称</th>
                            <th>类型</th>
                            <th>型号</th>
                            <th>日租金</th>
                            <th>位置</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        devices.forEach(device => {
            html += `
                <tr>
                    <td>${device.device_name}</td>
                    <td>${device.device_type}</td>
                    <td>${device.model || 'N/A'}</td>
                    <td>¥${device.daily_rate || 'N/A'}</td>
                    <td>${device.location || 'N/A'}</td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
        
        resultsDiv.innerHTML = html;
    }
    
    updateStats() {
        // 更新统计信息
        document.getElementById('total-devices').textContent = this.devices.length;
        document.getElementById('available-devices').textContent = 
            this.devices.filter(d => d.status === 'available').length;
        document.getElementById('active-rentals').textContent = 
            this.rentals.filter(r => r.status === 'active').length;
        
        // 计算逾期租赁
        const today = new Date();
        const overdueCount = this.rentals.filter(r => 
            r.status === 'active' && new Date(r.end_date) < today
        ).length;
        document.getElementById('overdue-rentals').textContent = overdueCount;
    }
    
    populateFilters() {
        // 设备类型字段当前未使用，避免渲染无效选项
        const typeFilter = document.getElementById('device-type-filter');
        if (typeFilter) {
            typeFilter.innerHTML = '<option value="">全部类型</option>';
        }
        
        // 填充位置过滤器
        const locationFilter = document.getElementById('location-filter');
        const locations = [...new Set(this.devices.map(d => d.location).filter(Boolean))];
        
        locations.forEach(location => {
            const option = document.createElement('option');
            option.value = location;
            option.textContent = location;
            locationFilter.appendChild(option);
        });
        
        // 填充查询模态框的设备类型
        const queryTypeFilter = document.getElementById('query-device-type');
        if (queryTypeFilter) {
            queryTypeFilter.innerHTML = '<option value="">全部类型</option>';
        }
    }
    
    applyFilters() {
        const deviceType = document.getElementById('device-type-filter').value;
        const deviceStatus = document.getElementById('device-status-filter').value;
        const location = document.getElementById('location-filter').value;
        
        // 过滤设备
        let filteredDevices = this.devices;
        
        if (deviceType) {
            filteredDevices = filteredDevices.filter(d => d.type === deviceType);
        }
        
        if (deviceStatus) {
            filteredDevices = filteredDevices.filter(d => d.status === deviceStatus);
        }
        
        if (location) {
            filteredDevices = filteredDevices.filter(d => d.location === location);
        }
        
        // 重新渲染甘特图
        this.devices = filteredDevices;
        this.renderGantt();
    }
    
    clearFilters() {
        document.getElementById('device-type-filter').value = '';
        document.getElementById('device-status-filter').value = '';
        document.getElementById('location-filter').value = '';
        
        // 重新加载所有数据
        this.loadData();
    }
    
    navigateDate(days) {
        this.startDate.setDate(this.startDate.getDate() + days);
        this.endDate.setDate(this.endDate.getDate() + days);
        this.currentDate.setDate(this.currentDate.getDate() + days);
        
        this.updateDateNavigation();
        this.loadData();
    }
    
    goToToday() {
        const today = new Date();
        this.startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        this.endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.currentDate = today;
        
        this.updateDateNavigation();
        this.loadData();
    }
    
    updateDateNavigation() {
        document.getElementById('current-period').textContent = 
            `${this.formatDate(this.startDate)} 至 ${this.formatDate(this.endDate)}`;
    }
    
    refreshData() {
        this.loadData();
    }
    
    // 工具方法
    formatDate(date) {
        // 使用本地时间，避免 toISOString 带来的时区回退（如 8 小时导致前一天）
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }
    
    isToday(date) {
        const today = new Date();
        return date.toDateString() === today.toDateString();
    }
    
    getDayName(date) {
        const days = ['日', '一', '二', '三', '四', '五', '六'];
        return days[date.getDay()];
    }

    // 如：1 日(周五)
    formatDateHeader(date) {
        const day = date.getDate();
        const week = this.getDayName(date);
        return `${day} 日(周${week})`;
    }

    // ---------------- 地区联动（省/市/区） ----------------
    initRegionSelectors() {
        // 优先使用用户提供的离线 JSON：/InventoryManager/pca-code.json
        // 结构：[{code,name,children:[{code,name,children:[{code,name}]}]}]
        const buildFromPca = (pca) => {
            const regions = {};
            pca.forEach(prov => {
                regions[prov.name] = {};
                (prov.children || []).forEach(city => {
                    regions[prov.name][city.name] = (city.children || []).map(a => a.name);
                });
            });
            return regions;
        };

        // 异步加载离线 JSON（不阻塞下拉初始化）
        this.REGIONS = {
            '北京市': { '北京市': ['东城区', '西城区', '朝阳区', '海淀区', '丰台区', '通州区'] },
            '上海市': { '上海市': ['黄浦区', '徐汇区', '长宁区', '浦东新区'] },
            '广东省': { '广州市': ['天河区', '越秀区', '荔湾区', '白云区'], '深圳市': ['南山区', '福田区', '罗湖区', '宝安区'] },
            '浙江省': { '杭州市': ['上城区', '拱墅区', '西湖区'], '宁波市': ['海曙区', '江北区'] }
        };
        // 从静态目录加载，附带时间戳避免缓存
        fetch(`/static/data/pca-code.json?t=${Date.now()}`, { cache: 'no-cache' })
            .then(res => res.ok ? res.json() : null)
            .then(pca => {
                if (!pca) return;
                this.REGIONS = buildFromPca(pca);
                // 用新数据重建三联动选项，尽量保留当前选择
                if (this.provinceSelect && this.citySelect && this.districtSelect) {
                    this.refreshRegionSelectOptions();
                }
            })
            .catch(() => {/* 静默失败，继续使用兜底数据 */});

        this.provinceSelect = document.getElementById('province-select');
        this.citySelect = document.getElementById('city-select');
        this.districtSelect = document.getElementById('district-select');

        if (!this.provinceSelect || !this.citySelect || !this.districtSelect) return;

        const fillOptions = (selectEl, items) => {
            const prev = selectEl.value;
            selectEl.innerHTML = '';
            items.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                selectEl.appendChild(opt);
            });
            // 恢复之前的选择（如果存在）
            if (items.includes(prev)) selectEl.value = prev;
        };

        // 省份
        fillOptions(this.provinceSelect, Object.keys(this.REGIONS));

        this.provinceSelect.oninput = () => {
            const prov = this.provinceSelect.value;
            const cities = prov && this.REGIONS[prov] ? Object.keys(this.REGIONS[prov]) : [];
            fillOptions(this.citySelect, cities);
            this.citySelect.oninput();
        };

        // 城市
        this.citySelect.oninput = () => {
            const prov = this.provinceSelect.value;
            const city = this.citySelect.value;
            const dists = prov && city && this.REGIONS[prov] && this.REGIONS[prov][city] ? this.REGIONS[prov][city] : [];
            fillOptions(this.districtSelect, dists);
        };

        // 注入下拉内搜索的样式
        this.injectFilterDropdownStyles();
        // 为三个选择框增加"展开后顶部可输入搜索"的下拉
        this.attachFilterDropdown(this.provinceSelect, () => Object.keys(this.REGIONS || {}), (val) => {
            if (!val) return;
            this.provinceSelect.value = val;
            this.provinceSelect.oninput();
        });
        this.attachFilterDropdown(this.citySelect, () => {
            const prov = this.provinceSelect.value; return prov ? Object.keys(this.REGIONS[prov] || {}) : [];
        }, (val) => {
            if (!val) return;
            this.citySelect.value = val;
            this.citySelect.oninput();
        });
        this.attachFilterDropdown(this.districtSelect, () => {
            const prov = this.provinceSelect.value; const city = this.citySelect.value;
            return prov && city ? (this.REGIONS[prov][city] || []) : [];
        }, (val) => {
            if (!val) return;
            this.districtSelect.value = val;
        });

        // 初始化一次
        this.provinceSelect.oninput();

        // 在模态框打开时再次兜底填充（防止某些浏览器延迟渲染导致元素未就绪）
        const modalEl = document.getElementById('bookingModal');
        if (modalEl) {
            modalEl.addEventListener('shown.bs.modal', () => {
                this.ensureRegionSelectorsPopulated();
            });
        }
    }

    // 填充设备下拉（新增租赁弹窗）
    populateDeviceSelect() {
        const sel = document.getElementById('device-select');
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">选择设备</option>';
        this.devices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.name}`;
            sel.appendChild(opt);
        });
        if (current) sel.value = current;
    }

    // 兜底保证省市区下拉有数据
    ensureRegionSelectorsPopulated() {
        this.provinceSelect = document.getElementById('province-select');
        this.citySelect = document.getElementById('city-select');
        this.districtSelect = document.getElementById('district-select');
        if (!this.provinceSelect || !this.citySelect || !this.districtSelect) return;
        if (this.provinceSelect.options.length === 0) {
            const provinces = Object.keys(this.REGIONS || {});
            if (provinces.length > 0) {
                const fill = (el, arr) => { el.innerHTML = ''; arr.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);}); };
                fill(this.provinceSelect, provinces);
                const firstProv = this.provinceSelect.value || provinces[0];
                const cities = firstProv && this.REGIONS[firstProv] ? Object.keys(this.REGIONS[firstProv]) : [];
                fill(this.citySelect, cities);
                const firstCity = this.citySelect.value || cities[0];
                const dists = firstProv && firstCity ? (this.REGIONS[firstProv][firstCity] || []) : [];
                fill(this.districtSelect, dists);
            }
        }
    }

    // 使用当前 REGIONS 重建省/市/区选项，尽量保留原选项
    refreshRegionSelectOptions() {
        const provinces = Object.keys(this.REGIONS || {});
        const prevProv = this.provinceSelect.value;
        const prevCity = this.citySelect.value;
        const prevDist = this.districtSelect.value;

        const fill = (el, arr) => { el.innerHTML = ''; arr.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);}); };

        fill(this.provinceSelect, provinces);
        const provToUse = provinces.includes(prevProv) ? prevProv : provinces[0];
        this.provinceSelect.value = provToUse;

        const cities = provToUse && this.REGIONS[provToUse] ? Object.keys(this.REGIONS[provToUse]) : [];
        fill(this.citySelect, cities);
        const cityToUse = cities.includes(prevCity) ? prevCity : cities[0];
        this.citySelect.value = cityToUse;

        const dists = provToUse && cityToUse ? (this.REGIONS[provToUse][cityToUse] || []) : [];
        fill(this.districtSelect, dists);
        const distToUse = dists.includes(prevDist) ? prevDist : dists[0];
        this.districtSelect.value = distToUse;
    }

    // 为原生 select 附加"展开后顶部可输入搜索"的下拉浮层
    attachFilterDropdown(selectEl, getAllItems, onPick) {
        if (!selectEl) return;
        let panel = null;
        let input = null;
        let list = null;

        const closePanel = () => {
            if (panel) panel.style.display = 'none';
        };

        const openPanel = () => {
            if (!panel) {
                panel = document.createElement('div');
                panel.className = 'filter-dropdown-panel';
                panel.innerHTML = `
                    <input class="filter-input" type="text" placeholder="搜索..." />
                    <div class="filter-list" role="listbox"></div>
                `;
                selectEl.parentElement.style.position = 'relative';
                selectEl.parentElement.appendChild(panel);
                input = panel.querySelector('.filter-input');
                list = panel.querySelector('.filter-list');
                input.addEventListener('input', () => renderList());
            }
            renderList();
            panel.style.display = 'block';
            input.value = '';
            input.focus();
        };

        const renderList = () => {
            const keyword = (input?.value || '').toLowerCase();
            const items = (getAllItems() || []).filter(v => v.toLowerCase().includes(keyword));
            list.innerHTML = '';
            items.forEach(v => {
                const a = document.createElement('div');
                a.className = 'filter-item';
                a.textContent = v;
                a.onclick = () => { onPick(v); closePanel(); };
                list.appendChild(a);
            });
        };

        // 打开下拉时显示搜索面板
        selectEl.addEventListener('mousedown', (e) => {
            // 延迟到浏览器展开原生下拉后再显示我们面板
            setTimeout(openPanel, 0);
        });
        // 滚动或点击外部关闭
        document.addEventListener('click', (e) => {
            if (!panel || panel.contains(e.target) || e.target === selectEl) return;
            closePanel();
        });
    }

    injectFilterDropdownStyles() {
        if (document.getElementById('filter-dropdown-style')) return;
        const style = document.createElement('style');
        style.id = 'filter-dropdown-style';
        style.textContent = `
        .filter-dropdown-panel{position:absolute;left:0;right:0;top:100%;z-index:1051;background:#fff;border:1px solid #dee2e6;border-radius:.25rem;box-shadow:0 .5rem 1rem rgba(0,0,0,.15);}
        .filter-dropdown-panel .filter-input{width:100%;padding:.375rem .75rem;border:none;border-bottom:1px solid #dee2e6;outline:none;}
        .filter-dropdown-panel .filter-list{max-height:240px;overflow:auto;}
        .filter-dropdown-panel .filter-item{padding:.375rem .75rem;cursor:pointer;}
        .filter-dropdown-panel .filter-item:hover{background:#f8f9fa;}
        `;
        document.head.appendChild(style);
    }
    
    getStatusText(status) {
        const statusMap = {
            'available': '可用',
            'rented': '已租出',
            'maintenance': '维护中',
            'retired': '已报废'
        };
        return statusMap[status] || status;
    }
    
    getRentalStatusText(status) {
        const statusMap = {
            'pending': '待审批',
            'active': '进行中',
            'completed': '已完成',
            'cancelled': '已取消',
            'overdue': '已逾期'
        };
        return statusMap[status] || status;
    }
    
    getErrorMessage(error) {
        try {
            if (error && error.response && error.response.data) {
                const data = error.response.data;
                if (typeof data === 'string') return data;
                return data.error || data.message || data.detail || JSON.stringify(data);
            }
            if (error && error.message) return error.message;
            return '请求失败';
        } catch (e) {
            return '请求失败';
        }
    }

    showToast(message, type = 'info') {
        // 简单的提示实现
        const alertClass = type === 'error' ? 'alert-danger' : 
                          type === 'success' ? 'alert-success' : 'alert-info';
        
        const toast = document.createElement('div');
        toast.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
        toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        toast.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(toast);
        
        // 自动消失
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 5000);
    }

    // 日历相关方法
    renderCalendar() {
        const calendarDays = document.getElementById('calendar-days');
        const currentMonthYear = document.getElementById('current-month-year');
        
        if (!calendarDays || !currentMonthYear) return;
        
        // 更新月份年份显示
        const year = this.calendarDate.getFullYear();
        const month = this.calendarDate.getMonth();
        currentMonthYear.textContent = `${year}年${month + 1}月`;
        
        // 获取当月第一天和最后一天
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const firstDayOfWeek = firstDay.getDay();
        const daysInMonth = lastDay.getDate();
        
        // 清空日历
        calendarDays.innerHTML = '';
        
        // 添加上个月的日期
        const prevMonth = new Date(year, month, 0);
        const daysInPrevMonth = prevMonth.getDate();
        for (let i = firstDayOfWeek - 1; i >= 0; i--) {
            const day = document.createElement('div');
            day.className = 'calendar-day other-month';
            day.textContent = daysInPrevMonth - i;
            day.onclick = () => this.selectDate(new Date(year, month - 1, daysInPrevMonth - i));
            calendarDays.appendChild(day);
        }
        
        // 添加当月的日期
        for (let day = 1; day <= daysInMonth; day++) {
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day';
            dayElement.textContent = day;
            
            const currentDate = new Date(year, month, day);
            
            // 检查是否是今天
            if (this.isToday(currentDate)) {
                dayElement.classList.add('today');
            }
            
            // 检查是否是已选择的开始日期
            if (this.selectedStartDate && this.isSameDate(currentDate, this.selectedStartDate)) {
                dayElement.classList.add('selected-start');
            }
            
            // 检查是否是已选择的结束日期
            if (this.selectedEndDate && this.isSameDate(currentDate, this.selectedEndDate)) {
                dayElement.classList.add('selected-end');
            }
            
            // 检查是否在选择的范围内
            if (this.selectedStartDate && this.selectedEndDate && 
                currentDate >= this.selectedStartDate && currentDate <= this.selectedEndDate) {
                dayElement.classList.add('in-range');
            }
            
            // 检查是否应该禁用（过去的日期）
            if (currentDate < new Date().setHours(0, 0, 0, 0)) {
                dayElement.classList.add('disabled');
            } else {
                dayElement.onclick = () => this.selectDate(currentDate);
            }
            
            calendarDays.appendChild(dayElement);
        }
        
        // 添加下个月的日期
        const remainingCells = 42 - (firstDayOfWeek + daysInMonth); // 6行7列 = 42
        for (let day = 1; day <= remainingCells; day++) {
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day other-month';
            dayElement.textContent = day;
            dayElement.onclick = () => this.selectDate(new Date(year, month + 1, day));
            calendarDays.appendChild(dayElement);
        }
        
        this.updateDateSelectionInfo();
    }
    
    selectDate(date) {
        if (date < new Date().setHours(0, 0, 0, 0)) {
            return; // 不能选择过去的日期
        }
        
        if (!this.isSelectingEnd) {
            // 第一次点击，选择开始日期
            this.selectedStartDate = new Date(date);
            this.selectedEndDate = null;
            this.isSelectingEnd = true;
            this.showToast('请选择结束日期', 'info');
        } else {
            // 第二次点击，选择结束日期
            if (date < this.selectedStartDate) {
                this.showToast('结束日期不能早于开始日期', 'error');
                return;
            }
            
            this.selectedEndDate = new Date(date);
            this.isSelectingEnd = false;
            this.showToast('日期选择完成，可以点击"找档期"按钮', 'success');
        }
        
        this.renderCalendar();
    }
    
    isSameDate(date1, date2) {
        return date1.getFullYear() === date2.getFullYear() &&
               date1.getMonth() === date2.getMonth() &&
               date1.getDate() === date2.getDate();
    }
    
    updateDateSelectionInfo() {
        const startDateSpan = document.getElementById('selected-start-date');
        const endDateSpan = document.getElementById('selected-end-date');
        
        if (startDateSpan) {
            startDateSpan.textContent = this.selectedStartDate ? 
                this.formatDate(this.selectedStartDate) : '未选择';
        }
        
        if (endDateSpan) {
            endDateSpan.textContent = this.selectedEndDate ? 
                this.formatDate(this.selectedEndDate) : '未选择';
        }
    }
    
    previousMonth() {
        this.calendarDate.setMonth(this.calendarDate.getMonth() - 1);
        this.renderCalendar();
    }
    
    nextMonth() {
        this.calendarDate.setMonth(this.calendarDate.getMonth() + 1);
        this.renderCalendar();
    }
    
    resetCalendarSelection() {
        this.selectedStartDate = null;
        this.selectedEndDate = null;
        this.isSelectingEnd = false;
        this.calendarDate = new Date();
        this.renderCalendar();
    }
}

// 全局变量
let ganttChart;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    ganttChart = new GanttChart();
});

// 全局函数
function navigateDate(days) {
    ganttChart.navigateDate(days);
}

function goToToday() {
    ganttChart.goToToday();
}

function refreshData() {
    ganttChart.refreshData();
}

function applyFilters() {
    ganttChart.applyFilters();
}

function clearFilters() {
    ganttChart.clearFilters();
}

function openBookingModal() {
    ganttChart.openBookingModal();
}

function submitBooking() {
    ganttChart.submitBooking();
}

function findAvailableSlot() {
    ganttChart.findAvailableSlot();
}

function updateRental() {
    ganttChart.updateRental();
}

function queryInventory() {
    ganttChart.queryInventory();
}

function previousMonth() {
    ganttChart.previousMonth();
}

function nextMonth() {
    ganttChart.nextMonth();
}
